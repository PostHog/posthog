import { HogFlowAction } from '~/cdp/schema/hogflow'
import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { workflowStepDispatchKeyFromInvocation } from '../../utils/workflow-step-dispatch-key'
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
        private frequencyCap?: { teamWorkflowsConfig: TeamWorkflowsConfigService; valkey: RedisV2 }
    ) {}

    /** Returns true when the person is at the cap. Otherwise records this send against the cap and returns false. */
    public async isFrequencyCapped(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<boolean> {
        const personId = invocation.state.globals.person?.id
        if (
            !this.frequencyCap ||
            !personId ||
            !this.isSubjectToRecipientPreferences(action) ||
            action.config.message_category_type === 'transactional'
        ) {
            return false
        }
        try {
            const { max_messages, window_days } = await this.frequencyCap.teamWorkflowsConfig.getFrequencyCap(
                invocation.teamId
            )
            if (!max_messages || !window_days) {
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

    public async shouldSkipAction(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<RecipientSkipReason | null> {
        if (!this.isSubjectToRecipientPreferences(action)) {
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

        return (await this.isRecipientOptedOutOfAction(invocation, action)) ? 'opted_out' : null
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

    private isSubjectToRecipientPreferences(action: HogFlowAction): action is MessageAction {
        return ['function_email', 'function_sms', 'function_push'].includes(action.type)
    }

    private async isRecipientOptedOutOfAction(
        invocation: CyclotronJobInvocationHogFunction,
        action: MessageAction
    ): Promise<boolean> {
        let identifier

        if (action.type === 'function_sms') {
            identifier = invocation.state.globals.inputs?.to_number
        } else if (action.type === 'function_email') {
            identifier = invocation.state.globals.inputs?.email?.to?.email
        } else if (action.type === 'function_push') {
            // Push has no email/phone "to" field. Delivery reads the device token from the invocation's
            // person (globals.person.properties), so key the opt-out on that same person's distinct_id —
            // not the configurable inputs.distinctId or the triggering event — so the recipient we check
            // is always the recipient we deliver to. Fall back to the event distinct_id when the person
            // has no resolved one.
            identifier = invocation.state.globals.person?.distinct_id ?? invocation.state.globals.event?.distinct_id
        }

        if (!identifier) {
            throw new Error(
                `No recipient identifier found for message action [Action:${action.id}]. Check that the message 'to' field is set correctly for this person.`
            )
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

            // Grab the recipient preferences for the action category
            const categoryId = action.config.message_category_id || '$all'

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
