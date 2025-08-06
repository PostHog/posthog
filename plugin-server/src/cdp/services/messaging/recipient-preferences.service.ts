import { HogFlowAction } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'

export class RecipientPreferencesService {
    constructor(private recipientsManager: RecipientsManagerService) {}

    public async shouldSkipAction(invocation: CyclotronJobInvocationHogFlow, action: HogFlowAction): Promise<boolean> {
        return (
            this.isSubjectToRecipientPreferences(action) && (await this.isRecipientOptedOutOfAction(invocation, action))
        )
    }

    private isSubjectToRecipientPreferences(
        action: HogFlowAction
    ): action is Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }> {
        return ['function_email', 'function_sms'].includes(action.type)
    }

    private async isRecipientOptedOutOfAction(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }>
    ): Promise<boolean> {
        // Get the identifier to be used from the action config for sms, this is an input called to_number,
        // for email it is inside an input called email, specifically email.to.
        let identifier

        if (action.type === 'function_sms') {
            identifier = action.config.inputs?.to_number
        } else if (action.type === 'function_email') {
            identifier = action.config.inputs?.email?.value?.to
        }

        if (!identifier) {
            throw new Error(`No identifier found for message action ${action.id}`)
        }

        try {
            const recipient = await this.recipientsManager.get({
                teamId: invocation.teamId,
                identifier: identifier,
            })

            if (recipient) {
                // Grab the recipient preferences for the action category
                const categoryId = action.config.message_category_id || '$all'

                const preference = this.recipientsManager.getPreference(recipient, categoryId)
                if (preference === 'OPTED_OUT') {
                    return true
                }
            }

            return false
        } catch (error) {
            // Log error but don't fail the execution
            console.error(`Failed to fetch recipient preferences for ${identifier}:`, error)
            return false
        }
    }
}
