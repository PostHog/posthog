import { Hub } from '~/types'
import { parseJSON } from '~/utils/json-parse'
import { logger } from '~/utils/logger'

import { HogFlowAction } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFunction } from '../../types'
import { JWT } from '../../utils/jwt-utils'
import { RecipientManagerRecipient, RecipientsManagerService } from '../managers/recipients-manager.service'

type MessageFunctionActionType = 'function_email' | 'function_sms'

type MessageAction = Extract<HogFlowAction, { type: MessageFunctionActionType }>

export class RecipientPreferencesService {
    private jwt: JWT

    constructor(
        protected hub: Hub,
        private recipientsManager: RecipientsManagerService
    ) {
        this.jwt = new JWT(hub)
    }

    public async shouldSkipAction(
        invocation: CyclotronJobInvocationHogFunction,
        action: HogFlowAction
    ): Promise<boolean> {
        return (
            this.isSubjectToRecipientPreferences(action) && (await this.isRecipientOptedOutOfAction(invocation, action))
        )
    }

    private isSubjectToRecipientPreferences(action: HogFlowAction): action is MessageAction {
        return ['function_email', 'function_sms'].includes(action.type)
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
        }

        if (!identifier) {
            throw new Error(`No identifier found for message action ${action.id}`)
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

    public validatePreferencesToken(
        token: string
    ): { valid: false } | { valid: true; team_id: number; identifier: string } {
        try {
            const decoded = this.jwt.verify(token, { ignoreVerificationErrors: true, maxAge: '7d' })
            if (!decoded) {
                return { valid: false }
            }

            const { team_id, identifier } = parseJSON(String(decoded))
            return { valid: true, team_id, identifier }
        } catch (error) {
            logger.error('Error validating preferences token:', error)
            return { valid: false }
        }
    }

    /**
     * Generate a secure, time-limited token for accessing preferences
     * This mirrors the Django implementation in message_preferences.py
     */
    private generatePreferencesToken(recipient: RecipientManagerRecipient): string {
        // Only identifier is encoded, as per JWT class
        // If you want to encode more, update JWT class to accept an object
        return this.jwt.sign(
            {
                team_id: recipient.team_id,
                identifier: recipient.identifier,
            },
            { expiresIn: '7d' }
        )
    }

    public async buildUnsubscribeUrl(
        invocation: CyclotronJobInvocationHogFunction,
        action: Extract<HogFlowAction, { type: 'function_email' }>
    ): Promise<string> {
        const recipient = await this.recipientsManager.get({
            teamId: invocation.teamId,
            identifier: action.config.inputs?.email?.value?.to,
        })

        if (!recipient) {
            throw new Error(
                `Could not generate unsubscribe URL, recipient not found for team ${invocation.teamId} and identifier: ${action.config.inputs?.email?.value?.to}`
            )
        }

        const token = this.generatePreferencesToken(recipient)
        return `${this.hub.SITE_URL}/messaging-preferences/${token}`
    }
}
