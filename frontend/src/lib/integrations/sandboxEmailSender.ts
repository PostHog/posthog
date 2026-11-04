export const isSandboxEmailSender = (integration: { kind: string; config?: unknown }): boolean =>
    integration.kind === 'email' && (integration.config as { provider?: unknown } | undefined)?.provider === 'sandbox'

export const SANDBOX_EMAIL_SENDER_NOTE = 'Delivers only to verified members of your organization.'
