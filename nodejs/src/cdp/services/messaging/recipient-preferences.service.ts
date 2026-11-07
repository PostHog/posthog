import { HogFlowAction } from '~/cdp/schema/hogflow'
import { acceptedSendEmailFields } from '~/cdp/services/hogflows/transactional-email'
import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFunction, MessageOptOutRecord } from '../../types'
import { NATIVE_PUSH_TEMPLATE_ID, pushRecipientOtherThanRunPerson } from '../../utils/push-subscription-utils'
import { workflowStepDispatchKeyFromInvocation } from '../../utils/workflow-step-dispatch-key'
import { PersonsManagerService } from '../managers/persons-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EmailSuppressionService } from './email-suppression.service'
import { removeSuppressedRecipients } from './helpers/suppressed-recipients'

type MessageFunctionActionType = 'function_email' | 'function_sms' | 'function_push'

type MessageAction = Extract<HogFlowAction, { type: MessageFunctionActionType }>

// Why the send was skipped, so callers can render a user-facing log/metric that names the actual
// reason instead of collapsing suppression and opt-out into a single "opted out" message.
export type RecipientSkipReason = 'suppressed' | 'opted_out'

// One Lua script, so two concurrent sends to one person cannot both pass with one slot left. KEYS[1] holds
// one entry per sent message, keyed on the step visit and scored by send time. The email queue and send
// retries run the same step visit again, so a visit that already holds a slot passes. That run also moves
// the slot score to now, because the email queue can delay the actual send by hours and the window must
// start when the email goes out.
//
// KEYS[2] is the line of held sends, scored by hold deadline, which is first-capped order while the
// team's hold length stays the same. A send gets a free slot only when every send ahead of it in line
// already has one, so a new send cannot take a slot that a held send is waiting for. Each held send
// leaves the line when it sends, when its deadline passes, or when it is released.
//
// A capped call returns the time in ms when this send's slot frees up, and an allowed call returns 0.
// The time assumes that each held send ahead takes the next slot that frees. A capped call with a hold
// deadline (ARGV[5], 0 for none) joins the line when that time is before the deadline and leaves it otherwise.
const FREQUENCY_CAP_SCRIPT = `
local now, window, max, member, deadline =
    tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4], tonumber(ARGV[5])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
local function take_slot()
    redis.call('ZREM', KEYS[2], member)
    redis.call('ZADD', KEYS[1], now, member)
    redis.call('PEXPIRE', KEYS[1], window)
    return 0
end
if redis.call('ZSCORE', KEYS[1], member) then
    return take_slot()
end
local ahead = redis.call('ZRANK', KEYS[2], member) or redis.call('ZCARD', KEYS[2])
local sent = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
if #sent / 2 + ahead < max then
    return take_slot()
end
local times = {}
for i = 2, #sent, 2 do
    times[#times + 1] = tonumber(sent[i])
end
local slot = now
for _ = 0, ahead do
    slot = now
    if #times >= max then
        slot = math.max(now, times[#times - max + 1] + window)
    end
    times[#times + 1] = slot
end
if deadline > 0 and slot < deadline then
    redis.call('ZADD', KEYS[2], 'NX', deadline, member)
    local last = redis.call('ZRANGE', KEYS[2], -1, -1, 'WITHSCORES')
    redis.call('PEXPIRE', KEYS[2], tonumber(last[2]) - now)
else
    redis.call('ZREM', KEYS[2], member)
end
return slot
`

export type FrequencyCapLine = { key: string; member: string }

export type FrequencyCapCheck =
    | { capped: false }
    // nextSlotAt is when this send can go out, in ms. hold is set when the send is in the line of held
    // sends and must wait until nextSlotAt, but not past deadlineAt. It is null when the send must skip.
    | { capped: true; nextSlotAt: number; hold: { deadlineAt: number; line: FrequencyCapLine } | null }

export type FrequencyCapHoldOptions = {
    // False for a send that cannot wait, which then skips when capped and leaves the line.
    canHold: boolean
    // The deadline of a send that is already held, in ISO format.
    deadlineAt?: string
}

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

    /** Reports whether the person is at the cap. When they are not, records this send against the cap. */
    public async checkFrequencyCap(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction,
        holdOptions: FrequencyCapHoldOptions = { canHold: false }
    ): Promise<FrequencyCapCheck> {
        const messageAction = this.asMessageAction(action)
        if (
            !this.frequencyCap ||
            !messageAction ||
            messageAction.config.message_category_type === 'transactional' ||
            (messageAction.type === 'function_email' && messageAction.config.skip_frequency_cap === true)
        ) {
            return { capped: false }
        }
        try {
            const { max_messages, window_days, hold_hours } =
                await this.frequencyCap.teamWorkflowsConfig.getFrequencyCap(invocation.teamId)
            if (!max_messages || !window_days) {
                return { capped: false }
            }
            const personId = await this.cappedPersonId(invocation, messageAction, this.frequencyCap.persons)
            if (!personId) {
                return { capped: false }
            }
            const now = Date.now()
            const deadlineAt =
                holdOptions.canHold && hold_hours
                    ? holdOptions.deadlineAt
                        ? Date.parse(holdOptions.deadlineAt)
                        : now + hold_hours * 60 * 60 * 1000
                    : 0
            const capKey = `@posthog/workflows-frequency-cap/${invocation.teamId}/${personId}`
            const line: FrequencyCapLine = {
                // The braces make Valkey cluster hash this key on capKey, so both keys of the script share
                // a slot. The capKey prefix keeps the key with the other keys of the team and person.
                key: `${capKey}/held{${capKey}}`,
                member: workflowStepDispatchKeyFromInvocation(invocation) ?? `${invocation.id}:${action.id}`,
            }
            const nextSlotAt = await this.frequencyCap.valkey.useClient(
                { name: 'workflows-frequency-cap', failOpen: true },
                (client) =>
                    client.eval(
                        FREQUENCY_CAP_SCRIPT,
                        2,
                        capKey,
                        line.key,
                        now,
                        window_days * 24 * 60 * 60 * 1000,
                        max_messages,
                        line.member,
                        deadlineAt
                    ) as Promise<number>
            )
            if (!nextSlotAt) {
                return { capped: false }
            }
            return {
                capped: true,
                nextSlotAt,
                hold: deadlineAt && nextSlotAt < deadlineAt ? { deadlineAt, line } : null,
            }
        } catch (error) {
            // Fail open: a config or Valkey pool error must never block a send. failOpen above only
            // covers errors inside the Valkey callback.
            logger.error(`Failed to check the frequency cap for team ${invocation.teamId}:`, error)
            return { capped: false }
        }
    }

    /** Removes a held send from the line, so the sends behind it do not wait for a send that will not happen. */
    public async releaseFrequencyCapHold(teamId: number, line: FrequencyCapLine): Promise<void> {
        if (!this.frequencyCap) {
            return
        }
        try {
            await this.frequencyCap.valkey.useClient({ name: 'workflows-frequency-cap', failOpen: true }, (client) =>
                client.zrem(line.key, line.member)
            )
        } catch (error) {
            // The held send leaves the line at its deadline anyway, so a failed release only delays the sends behind it.
            logger.error(`Failed to release a frequency cap hold for team ${teamId}:`, error)
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

        // Suppression is mostly a deliverability signal, not a messaging preference. We check it even for
        // transactional messages, and before the transactional opt-out bypass below. For those, only a hard
        // bounce blocks the send, because then the address can't receive mail.
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

        // Skip only when `to` is suppressed and no cc address can take its place. EmailService
        // removes the other suppressed addresses at send time, and the email still goes to the rest.
        const emailInputs = {
            ...invocation.state.globals.inputs?.email,
            ...acceptedSendEmailFields(invocation.state.send),
        }
        try {
            const result = await removeSuppressedRecipients(
                {
                    to: { email: typeof emailInputs?.to?.email === 'string' ? emailInputs.to.email : undefined },
                    cc: typeof emailInputs?.cc === 'string' ? emailInputs.cc : undefined,
                    bcc: typeof emailInputs?.bcc === 'string' ? emailInputs.bcc : undefined,
                },
                (email) =>
                    this.emailSuppressionService.isSuppressed(invocation.teamId, email, {
                        transactional: action.config.message_category_type === 'transactional',
                    })
            )
            return result.skip
        } catch (error) {
            // Fail open — never block a send on a suppression-lookup error.
            logger.error(`Failed to check suppression list for team ${invocation.teamId}:`, error)
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
