import { IntegrationKind, IntegrationType } from '~/types'

import { VercelIntegrationSuffix } from './VercelIntegrationSuffix'

export type OrganizationIntegrationConfig = {
    getSuffix: (integration: IntegrationType) => JSX.Element | undefined
    getDisplayName: (integration: IntegrationType) => string
}

const INTEGRATION_CONFIGS: Partial<Record<IntegrationKind, OrganizationIntegrationConfig>> = {
    vercel: {
        getSuffix: (integration) => <VercelIntegrationSuffix integration={integration} />,
        getDisplayName: (integration) => integration.config?.account?.name || integration.display_name,
    },
}

const DEFAULT_INTEGRATION_CONFIG: OrganizationIntegrationConfig = {
    getSuffix: () => undefined,
    getDisplayName: (integration) => integration.display_name,
}

export const getIntegrationConfig = (kind: IntegrationKind): OrganizationIntegrationConfig => {
    return INTEGRATION_CONFIGS[kind] || DEFAULT_INTEGRATION_CONFIG
}
