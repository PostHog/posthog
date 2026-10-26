import { HogFlowAction } from '~/cdp/schema/hogflow'
import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFunction, MessageOptOutRecord } from '../../types'
import { NATIVE_PUSH_TEMPLATE_ID, pushRecipientOtherThanRunPerson } from '../../utils/push-subscription-utils'
import { workflowStepDispatchKeyFromInvocation } from '../../utils/workflow-step-dispatch-key'
import { PersonsManagerService } from '../managers/persons-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EmailSuppressionService } from './email-suppression.service'

type MessageFunctionActionType = 'function_email' | 'function_sms' | 'function_push'

type MessageAction = Extract<HogFlowAction, { type: MessageFunctionActionType }>

// Why the send was skipped, so callers can render a user-facing log/metric that names the actual
// reason instead of collapsing suppression and opt-out into a single "opted out" message.
export type RecipientSkipReason = 'suppressed' | 'opted_out'

// Split a comma-separated address list and, for each entry, extract the bare email from an RFC-822
// `"Name" <email@x>` form so it can be matched against normalized suppression identifiers.
const extractEmailsFromAddressList = (value: unknown): string[] => {
    if (typeof value !== 'string' || value.trim().length === 0) {
        return []
    }
    return value
        .split(',')
        .map((raw) => {
            const trimmed = raw.trim()
            const bracketed = trimmed.match(/<([^>]+)>/)
            return (bracketed ? bracketed[1] : trimmed).trim()
        })
        .filter((addr) => addr.length > 0)
}

// One Lua script, so two concurrent sends to one person cannot both pass with one slot left. Each slot
// is keyed on the step visit. The email queue and send retries run the same step visit again, so a
// visit that already holds a slot passes. That run also moves the slot score to now, because the email
// queue can delay the actual send by hours and the window must start when the email goes out.
const FREQUENCY_CAP_SCRIPT = `
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))
if not redis.call('ZSCORE', KEYS[1], ARGV[4]) and redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 1 end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 0
`

export class RecipientPreferencesService {
    constructor(
        private recipientsManager: RecipientsManagerService,
        private emailSuppressionService: EmailSuppressionService,
        private frequencyCap?: {
            teamWorkflowsConfig: TeamWorkflowsConfigService
            valkey: RedisV2
            persons: Pick<PersonsManagerService, 'getCyclotronPerson'>
        }
    ) {}

    /** Returns true when the person is at the cap. Otherwise records this send against the cap and returns false. */
    public async isFrequencyCapped(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<boolean> {
        const messageAction = this.asMessageAction(action)
        if (!this.frequencyCap || !messageAction || messageAction.config.message_category_type === 'transactional') {
            return false
        }
        try {
            const { max_messages, window_days } = await this.frequencyCap.teamWorkflowsConfig.getFrequencyCap(
                invocation.teamId
            )
            if (!max_messages || !window_days) {
                return false
            }
            const personId = await this.cappedPersonId(invocation, messageAction, this.frequencyCap.persons)
            if (!personId) {
                return false
            }
            const capped = await this.frequencyCap.valkey.useClient(
                { name: 'workflows-frequency-cap', failOpen: true },
                (client) =>
                    client.eval(
                        FREQUENCY_CAP_SCRIPT,
                        1,
                        `@posthog/workflows-frequency-cap/${invocation.teamId}/${personId}`,
                        Date.now(),
                        window_days * 24 * 60 * 60 * 1000,
                        max_messages,
                        workflowStepDispatchKeyFromInvocation(invocation) ?? `${invocation.id}:${action.id}`
                    ) as Promise<number>
            )
            return capped === 1
        } catch (error) {
            // Fail open: a config or Valkey pool error must never block a send. failOpen above only
            // covers errors inside the Valkey callback.
            logger.error(`Failed to check the frequency cap for team ${invocation.teamId}:`, error)
            return false
        }
    }

    private async cappedPersonId(
        invocation: CyclotronJobInvocationHogFunction,
        action: MessageAction,
        persons: Pick<PersonsManagerService, 'getCyclotronPerson'>
    ): Promise<string | undefined> {
        const { globals } = invocation.state
        const named =
            action.type === 'function_push'
                ? pushRecipientOtherThanRunPerson(globals.inputs?.distinctId, globals)
                : null
        if (!named) {
            return globals.person?.id
        }
        return (await persons.getCyclotronPerson(invocation.teamId, named, 'distinct_id'))?.id
    }

    public async shouldSkipAction(
        invocation: CyclotronJobInvocationHogFunction,
        hogFlowAction: HogFlowAction,
        runOptOuts: MessageOptOutRecord[] = []
    ): Promise<RecipientSkipReason | null> {
        const action = this.asMessageAction(hogFlowAction)
        if (!action) {
            return null
        }

        // Suppression is a deliverability signal, not a messaging preference: an address that can't
        // receive mail can't receive it regardless of category. So we check it even for
        // transactional messages, and before the transactional opt-out bypass below.
        if (await this.isRecipientSuppressed(invocation, action)) {
            return 'suppressed'
        }

        // Transactional messages are not eligible for opt-outs, so they send regardless of
        // whether the recipient has opted out of this category or of all marketing messaging.
        if (action.config.message_category_type === 'transactional') {
            return null
        }

        return (await this.isRecipientOptedOutOfAction(invocation, action, runOptOuts)) ? 'opted_out' : null
    }

    private async isRecipientSuppressed(
        invocation: CyclotronJobInvocationHogFunction,
        action: MessageAction
    ): Promise<boolean> {
        // Suppression is driven by email bounces, so it only applies to email sends.
        if (action.type !== 'function_email') {
            return false
        }

        // Check every destination address SES will see — `to`, `cc`, and `bcc`. A suppressed
        // address in any of the three blocks the send, not just when it appears in `to`.
        const emailInputs = invocation.state.globals.inputs?.email
        const to = emailInputs?.to?.email
        const recipients = [
            ...(typeof to === 'string' && to.trim() ? [to.trim()] : []),
            ...extractEmailsFromAddressList(emailInputs?.cc),
            ...extractEmailsFromAddressList(emailInputs?.bcc),
        ]

        if (recipients.length === 0) {
            return false
        }

        try {
            const results = await Promise.all(
                recipients.map((email) => this.emailSuppressionService.isSuppressed(invocation.teamId, email))
            )
            return results.some(Boolean)
        } catch (error) {
            // Fail open — never block a send on a suppression-lookup error.
            logger.error(`Failed to check suppression list for recipients ${recipients.join(', ')}:`, error)
            return false
        }
    }

    // A generic function step saved through the API can run the push template, and it then sends like a push step.
    private asMessageAction(action: HogFlowAction): MessageAction | null {
        if (['function_email', 'function_sms', 'function_push'].includes(action.type)) {
            return action as MessageAction
        }
        if (action.type === 'function' && action.config.template_id === NATIVE_PUSH_TEMPLATE_ID) {
            return { ...action, type: 'function_push' } as unknown as MessageAction
        }
        return null
    }

    private async isRecipientOptedOutOfAction(
        invocation: CyclotronJobInvocationHogFunction,
        action: MessageAction,
        runOptOuts: MessageOptOutRecord[]
    ): Promise<boolean> {
        let identifier

        if (action.type === 'function_sms') {
            identifier = invocation.state.globals.inputs?.to_number
        } else if (action.type === 'function_email') {
            identifier = invocation.state.globals.inputs?.email?.to?.email
        } else if (action.type === 'function_push') {
            // Push has no email/phone "to" field. Key the opt-out on the person the push is delivered to:
            // the person the Distinct ID input names, or the run's person when it names them. Fall back to
            // the event distinct_id when the run's person has no resolved one.
            const { globals } = invocation.state
            identifier =
                pushRecipientOtherThanRunPerson(globals.inputs?.distinctId, globals) ??
                globals.person?.distinct_id ??
                globals.event?.distinct_id
        }

        if (!identifier) {
            // EmailService skips a send with no `to` and records email_missing_recipient, so let it through.
            if (action.type === 'function_email') {
                return false
            }
            throw new Error(
                `No recipient identifier found for message action [Action:${action.id}]. Check that the message 'to' field is set correctly for this person.`
            )
        }

        // Grab the recipient preferences for the action category
        const categoryId = action.config.message_category_id || '$all'
        const trimmedIdentifier = String(identifier).trim()
        if (
            runOptOuts.some(
                (optOut) =>
                    optOut.identifier === trimmedIdentifier &&
                    (optOut.categoryId === categoryId || optOut.categoryId === '$all')
            )
        ) {
            return true
        }

        try {
            const recipient = await this.recipientsManager.get({
                teamId: invocation.teamId,
                identifier: identifier,
            })

            if (!recipient) {
                /**
                 * If the recipient lookup succeeded and the recipient doesn't exist, default to `false`
                 * as it is the Messaging customer's responsibility to ensure new users opt-in to messaging
                 * during onboarding.
                 */
                return false
            }

            const messageCategoryPreference = this.recipientsManager.getPreference(recipient, categoryId)
            const allMarketingPreferences = this.recipientsManager.getAllMarketingMessagingPreference(recipient)

            /**
             * NB: A recipient may have opted out of all marketing messaging but NOT a specific category,
             * so we always check both.
             *
             * This would commonly happen if the recipient opted out before the category was created.
             */
            return messageCategoryPreference === 'OPTED_OUT' || allMarketingPreferences === 'OPTED_OUT'
        } catch (error) {
            logger.error(`Failed to fetch recipient preferences for ${identifier}:`, error)
            return false
        }
    }
}
