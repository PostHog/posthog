import { Hub } from '~/types'
import { logger } from '~/utils/logger'

import { JWT, PosthogJwtAudience } from '../../utils/jwt-utils'
import { RecipientManagerRecipient } from '../managers/recipients-manager.service'

export class RecipientTokensService {
    private jwt: JWT

    constructor(protected hub: Pick<Hub, 'ENCRYPTION_SALT_KEYS' | 'SITE_URL'>) {
        this.jwt = new JWT(hub.ENCRYPTION_SALT_KEYS ?? '')
    }

    public validatePreferencesToken(
        token: string
    ): { valid: false } | { valid: true; team_id: number; identifier: string } {
        try {
            const decoded = this.jwt.verify(token, PosthogJwtAudience.SUBSCRIPTION_PREFERENCES, {
                ignoreVerificationErrors: true,
                maxAge: '7d',
            })
            if (!decoded) {
                return { valid: false }
            }

            const { team_id, identifier } = decoded as { team_id: number; identifier: string }
            return { valid: true, team_id, identifier }
        } catch (error) {
            logger.error('Error validating preferences token:', error)
            return { valid: false }
        }
    }

    public generatePreferencesToken(recipient: Pick<RecipientManagerRecipient, 'team_id' | 'identifier'>): string {
        return this.jwt.sign(
            {
                team_id: recipient.team_id,
                identifier: recipient.identifier,
            },
            PosthogJwtAudience.SUBSCRIPTION_PREFERENCES,
            { expiresIn: '7d' }
        )
    }

    public generatePreferencesUrl(recipient: Pick<RecipientManagerRecipient, 'team_id' | 'identifier'>): string {
        const token = this.generatePreferencesToken(recipient)
        return `${this.hub.SITE_URL}/messaging-preferences/${token}/` // NOTE: Trailing slash is required for the preferences page to work
    }
}
