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
}

export type ValidatedPreferencesToken =
    | { valid: false }
    | { valid: true; team_id: number; identifier: string; app_source_id?: string; instance_id?: string }

export function preferencesTokenSourceForInvocation(
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'parentRunId' | 'state'>
): PreferencesTokenSource | undefined {
    // Hog function destinations send email too, but only hog flow metrics are keyed this way.
    if (!('hogFlow' in invocation)) {
        return undefined
    }
    return {
        appSourceId: invocation.parentRunId ?? invocation.functionId,
        instanceId: invocation.state.actionId || undefined,
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

            const { team_id, identifier, app_source_id, instance_id } = decoded as {
                team_id: number
                identifier: string
                app_source_id?: unknown
                instance_id?: unknown
            }
            return {
                valid: true,
                team_id,
                identifier,
                ...(typeof app_source_id === 'string' ? { app_source_id } : {}),
                ...(typeof instance_id === 'string' ? { instance_id } : {}),
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
