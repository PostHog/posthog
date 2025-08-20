import * as crypto from 'crypto'

import { parseJSON } from '~/utils/json-parse'

import { HogFlowAction } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFunction } from '../../types'
import { RecipientManagerRecipient, RecipientsManagerService } from '../managers/recipients-manager.service'

type MessageFunctionActionType = 'function_email' | 'function_sms'

type MessageAction = Extract<HogFlowAction, { type: MessageFunctionActionType }>

export class RecipientPreferencesService {
    constructor(private recipientsManager: RecipientsManagerService) {}

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
            // Log error but don't fail the execution
            console.error(`Failed to fetch recipient preferences for ${identifier}:`, error)
            return false
        }
    }

    public validatePreferencesToken(token: string): { valid: boolean; team_id?: number; identifier?: string } {
        try {
            const secretKey = 'TODO_PICK_REAL_SECRET_KEY'

            // Token format: timestamp.payload.signature
            const parts = token.split('.')
            if (parts.length !== 3) {
                return { valid: false }
            }

            const [timestamp, payloadBase64, signature] = parts

            // Check if token is expired (7 days)
            const tokenAge = Date.now() - parseInt(timestamp)
            const maxAge = 7 * 24 * 60 * 60 * 1000 // 7 days in milliseconds
            if (tokenAge > maxAge) {
                return { valid: false }
            }

            // Verify signature
            const expectedSignature = crypto
                .createHmac('sha256', secretKey)
                .update(`${timestamp}.${payloadBase64}`)
                .digest('hex')

            if (signature !== expectedSignature) {
                return { valid: false }
            }

            // Decode payload
            const payload = parseJSON(Buffer.from(payloadBase64, 'base64').toString('utf8'))

            return {
                valid: true,
                team_id: payload.team_id,
                identifier: payload.identifier,
            }
        } catch (error) {
            console.error('Error validating preferences token:', error)
            return { valid: false }
        }
    }

    /**
     * Generate a secure, time-limited token for accessing preferences
     * This mirrors the Django implementation in message_preferences.py
     */
    private generatePreferencesToken(recipient: RecipientManagerRecipient): string {
        const secretKey = 'TODO_PICK_REAL_SECRET_KEY'

        const timestamp = Date.now().toString()
        const payload = JSON.stringify({
            team_id: recipient.team_id,
            identifier: recipient.identifier,
        })

        // Encode payload to base64 for URL safety
        const payloadBase64 = Buffer.from(payload).toString('base64')

        // Create signature
        const signature = crypto.createHmac('sha256', secretKey).update(`${timestamp}.${payloadBase64}`).digest('hex')

        // Token format: timestamp.payload.signature
        return `${timestamp}.${payloadBase64}.${signature}`
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
