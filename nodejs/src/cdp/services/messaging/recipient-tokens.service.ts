import { logger } from '~/common/utils/logger'

import type { CyclotronJobInvocationHogFunction } from '../../types'
import { JWT, PosthogJwtAudience } from '../../utils/jwt-utils'
import { RecipientManagerRecipient } from '../managers/recipients-manager.service'

type PreferencesRecipient = Pick<RecipientManagerRecipient, 'team_id' | 'identifier'>

/** The workflow email a preferences link came from, so an opt-out can be counted against it. */
export type PreferencesTokenSource = {
    /** The key the email's other metrics use: the batch run id for a broadcast, otherwise the hog flow id. */
    appSourceId: string
    /** The email action id. */
    instanceId?: string
    workflowId: string
    invocationId: string
    workflowVersion?: number
}

export type ValidatedPreferencesToken =
    | { valid: false }
    | {
          valid: true
          team_id: number
          identifier: string
          app_source_id?: string
          instance_id?: string
          workflow_id?: string
          invocation_id?: string
          workflow_version?: number
      }

export function preferencesTokenSourceForInvocation(
    invocation: Pick<CyclotronJobInvocationHogFunction, 'id' | 'functionId' | 'parentRunId' | 'state'>
): PreferencesTokenSource | undefined {
    // Hog function destinations send email too, but only hog flow metrics are keyed this way.
    if (!('hogFlow' in invocation)) {
        return undefined
    }
    return {
        appSourceId: invocation.parentRunId ?? invocation.functionId,
        instanceId: invocation.state.actionId || undefined,
        workflowId: invocation.functionId,
        invocationId: invocation.id,
        workflowVersion: invocation.state.renderedWorkflowVersion,
    }
}

export class RecipientTokensService {
    private jwt: JWT

    constructor(
        private encryptionSaltKeys: string,
        private siteUrl: string
    ) {
        this.jwt = new JWT(encryptionSaltKeys ?? '')
    }

    public validatePreferencesToken(token: string): ValidatedPreferencesToken {
        try {
            const decoded = this.jwt.verify(token, PosthogJwtAudience.SUBSCRIPTION_PREFERENCES, {
                ignoreVerificationErrors: true,
                maxAge: '7d',
            })
            if (!decoded) {
                return { valid: false }
            }

            const { team_id, identifier, app_source_id, instance_id, workflow_id, invocation_id, workflow_version } =
                decoded as {
                    team_id: number
                    identifier: string
                    app_source_id?: unknown
                    instance_id?: unknown
                    workflow_id?: unknown
                    invocation_id?: unknown
                    workflow_version?: unknown
                }
            return {
                valid: true,
                team_id,
                identifier,
                ...(typeof app_source_id === 'string' ? { app_source_id } : {}),
                ...(typeof instance_id === 'string' ? { instance_id } : {}),
                ...(typeof workflow_id === 'string' ? { workflow_id } : {}),
                ...(typeof invocation_id === 'string' ? { invocation_id } : {}),
                ...(typeof workflow_version === 'number' ? { workflow_version } : {}),
            }
        } catch (error) {
            logger.error('Error validating preferences token:', error)
            return { valid: false }
        }
    }

    public generatePreferencesToken(recipient: PreferencesRecipient, source?: PreferencesTokenSource): string {
        return this.jwt.sign(
            {
                team_id: recipient.team_id,
                identifier: recipient.identifier,
                ...(source ? { app_source_id: source.appSourceId } : {}),
                ...(source?.instanceId ? { instance_id: source.instanceId } : {}),
                ...(source ? { workflow_id: source.workflowId, invocation_id: source.invocationId } : {}),
                ...(source?.workflowVersion !== undefined ? { workflow_version: source.workflowVersion } : {}),
            },
            PosthogJwtAudience.SUBSCRIPTION_PREFERENCES,
            { expiresIn: '7d' }
        )
    }

    public generatePreferencesUrl(recipient: PreferencesRecipient, source?: PreferencesTokenSource): string {
        const token = this.generatePreferencesToken(recipient, source)
        return `${this.siteUrl}/messaging-preferences/${token}/` // NOTE: Trailing slash is required for the preferences page to work
    }

    public generateOneClickUnsubscribeUrl(recipient: PreferencesRecipient, source?: PreferencesTokenSource): string {
        return `${this.generatePreferencesUrl(recipient, source)}?one_click_unsubscribe=1`
    }
}
