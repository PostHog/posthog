import { HogFlowAction } from '~/cdp/schema/hogflow'
import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { EmailSuppressionService } from './email-suppression.service'

type MessageFunctionActionType = 'function_email' | 'function_sms' | 'function_push'

type MessageAction = Extract<HogFlowAction, { type: MessageFunctionActionType }>

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

export class RecipientPreferencesService {
    constructor(
        private recipientsManager: RecipientsManagerService,
        private emailSuppressionService: EmailSuppressionService
    ) {}

    public async shouldSkipAction(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<boolean> {
        if (!this.isSubjectToRecipientPreferences(action)) {
            return false
        }

        // Suppression is a deliverability signal, not a messaging preference: an address that can't
        // receive mail can't receive it regardless of category. So we check it even for
        // transactional messages, and before the transactional opt-out bypass below.
        if (await this.isRecipientSuppressed(invocation, action)) {
            return true
        }

        // Transactional messages are not eligible for opt-outs, so they send regardless of
        // whether the recipient has opted out of this category or of all marketing messaging.
        if (action.config.message_category_type === 'transactional') {
            return false
        }

        return await this.isRecipientOptedOutOfAction(invocation, action)
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
