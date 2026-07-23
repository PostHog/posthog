/**
 * A raw row from `posthog_integration`, with `sensitive_config` still Fernet-encrypted.
 */
export interface IntegrationRow {
    id: number
    team_id: number
    kind: string
    config: Record<string, any>
    sensitive_config: Record<string, any>
}

/**
 * A decrypted, cacheable integration. Serializes to exactly the shape the plugin-server's
 * `IntegrationType` (`~/cdp/types`) expects, so the CDP consumer swap is a drop-in.
 */
export interface DecryptedIntegration {
    id: number
    team_id: number
    kind: string
    config: Record<string, any>
    sensitive_config: Record<string, any>
}
