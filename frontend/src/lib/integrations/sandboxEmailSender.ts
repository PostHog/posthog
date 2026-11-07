const hasSandboxProvider = (config: unknown): boolean =>
    typeof config === 'object' && config !== null && 'provider' in config && config.provider === 'sandbox'

export const isSandboxEmailSender = (integration: { kind: string; config?: unknown }): boolean =>
    integration.kind === 'email' && hasSandboxProvider(integration.config)

export const SANDBOX_EMAIL_SENDER_NOTE = 'Delivers only to verified members of your organization.'
