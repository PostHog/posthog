import { identifierToHuman } from 'lib/utils/strings'

import type { ActivityLogCredentialTypeEnumApi } from 'products/platform_features/frontend/generated/api.schemas'

const CREDENTIAL_TYPE_LABELS: Record<ActivityLogCredentialTypeEnumApi, string> = {
    session: 'Session',
    personal_api_key: 'Personal API key',
    oauth: 'OAuth app',
    project_secret_key: 'Project secret API key',
    team_secret_token: 'Legacy secret key',
    id_jag: 'Cross-app access (XAA)',
    oidc_workload: 'Trusted workload',
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

export function credentialTypeLabel(credentialType: ActivityLogCredentialTypeEnumApi): string {
    // A cached frontend bundle can receive a type that a newer backend added after the bundle was built.
    return CREDENTIAL_TYPE_LABELS[credentialType] ?? identifierToHuman(credentialType)
}
