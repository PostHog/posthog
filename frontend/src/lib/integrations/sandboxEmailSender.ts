import type { IntegrationType } from '~/types'

export const isSandboxEmailSender = (integration: Pick<IntegrationType, 'kind' | 'config'>): boolean =>
    integration.kind === 'email' && integration.config?.provider === 'sandbox'

export const SANDBOX_EMAIL_SENDER_NOTE = 'Delivers only to verified members of your organization.'
