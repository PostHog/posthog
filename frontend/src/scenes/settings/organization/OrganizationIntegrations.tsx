import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationConfig } from 'lib/integrations/organizationIntegrationConfig'

import { IntegrationType } from '~/types'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

export function OrganizationIntegrations(): JSX.Element | null {
    const { organizationIntegrations, organizationIntegrationsLoading } = useValues(organizationIntegrationsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (organizationIntegrationsLoading) {
        return todayRailNav ? (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-16" />
                <Skeleton className="h-16" />
            </div>
        ) : (
            <div className="space-y-2">
                <LemonSkeleton className="h-16" />
                <LemonSkeleton className="h-16" />
            </div>
        )
    }

    if (!organizationIntegrations || organizationIntegrations.length === 0) {
        return null
    }

    return (
        <div className={todayRailNav ? 'flex flex-col gap-2' : 'space-y-2'}>
            {organizationIntegrations.map((integration: IntegrationType) => {
                const config = getIntegrationConfig(integration.kind)

                return (
                    <IntegrationView
                        key={integration.id}
                        integration={{
                            ...integration,
                            display_name: config.getDisplayName(integration),
                        }}
                        suffix={config.getSuffix(integration)}
                    />
                )
            })}
        </div>
    )
}
