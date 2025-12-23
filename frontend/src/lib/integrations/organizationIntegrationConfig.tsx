import { LemonButton } from '@posthog/lemon-ui'

import { IntegrationKind, IntegrationType } from '~/types'

import { VercelIntegrationSuffix } from './VercelIntegrationSuffix'

export type OrganizationIntegrationConfig = {
    getSuffix: (integration: IntegrationType, onDelete: () => void, disabledReason?: string) => JSX.Element
    getDisplayName: (integration: IntegrationType) => string
}

const INTEGRATION_CONFIGS: Partial<Record<IntegrationKind, OrganizationIntegrationConfig>> = {
    vercel: {
        getSuffix: (integration, onDelete, disabledReason) => (
            <VercelIntegrationSuffix integration={integration} onDelete={onDelete} disabledReason={disabledReason} />
        ),
        getDisplayName: (integration) => integration.config?.account?.name || integration.display_name,
    },
}

export const getDefaultIntegrationConfig = (): OrganizationIntegrationConfig => ({
    getSuffix: (_integration, onDelete, disabledReason) => (
        <LemonButton type="secondary" status="danger" onClick={onDelete} disabledReason={disabledReason}>
            Disconnect
        </LemonButton>
    ),
    getDisplayName: (integration) => integration.display_name,
})

export const getIntegrationConfig = (kind: IntegrationKind): OrganizationIntegrationConfig => {
    return INTEGRATION_CONFIGS[kind] || getDefaultIntegrationConfig()
}
