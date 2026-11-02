import { capitalizeFirstLetter } from 'lib/utils/strings'

const CREDENTIAL_TYPE_LABELS: Record<string, string> = {
    session: 'Session',
    personal_api_key: 'Personal API key',
    oauth: 'OAuth app',
    project_secret_key: 'Project secret key',
    team_secret_token: 'Legacy secret key',
    id_jag: 'Cross-app access (XAA)',
    scim: 'SCIM',
    vercel: 'Vercel',
    partner: 'Partner app',
    sharing_access_token: 'Shared link',
    sharing_password: 'Shared link password',
    widget_token: 'Widget token',
    gateway_agent: 'MCP gateway agent',
    export_renderer: 'Export',
    webhook: 'Webhook',
    internal_jwt: 'PostHog service',
    service_jwt: 'PostHog service',
    internal_api_secret: 'PostHog service',
    cross_region_signature: 'PostHog service',
    billing_service: 'PostHog billing',
    unattributed: 'Unknown',
}

export function credentialTypeLabel(credentialType: string): string {
    return CREDENTIAL_TYPE_LABELS[credentialType] ?? capitalizeFirstLetter(credentialType.replaceAll('_', ' '))
}
