import { useActions, useValues } from 'kea'

import { IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { ICONS } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'

import { calendarSyncLogic } from './calendarSyncLogic'

export function CalendarSyncConfig(): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)
    const { statusByIntegrationId, triggeringIntegrationIds } = useValues(calendarSyncLogic)
    const { syncNow } = useActions(calendarSyncLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const calendarIntegrations = integrations?.filter((integration) => integration.kind === 'google-calendar') ?? []

    return (
        <div className="flex flex-col gap-4">
            {calendarIntegrations.map((integration) => {
                const syncStatus = statusByIntegrationId[integration.id]
                const isSyncing = !!syncStatus?.is_syncing || triggeringIntegrationIds.includes(integration.id)
                return (
                    <IntegrationView
                        key={integration.id}
                        integration={integration}
                        // A custom suffix replaces IntegrationView's built-in Disconnect button, so it returns here.
                        suffix={
                            <div className="flex flex-row items-center gap-2">
                                <span className="text-xs text-secondary whitespace-nowrap">
                                    {isSyncing ? (
                                        'Syncing...'
                                    ) : syncStatus?.last_synced_at ? (
                                        <>
                                            Last synced <TZLabel time={syncStatus.last_synced_at} />
                                        </>
                                    ) : (
                                        'Not synced yet'
                                    )}
                                </span>
                                <LemonButton
                                    type="secondary"
                                    icon={<IconRefresh />}
                                    loading={isSyncing}
                                    disabledReason={isSyncing ? 'A sync is already running' : restrictedReason}
                                    onClick={() => syncNow(integration.id)}
                                >
                                    Sync now
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    icon={<IconTrash />}
                                    onClick={() => deleteIntegration(integration.id)}
                                    disabledReason={restrictedReason}
                                >
                                    Disconnect
                                </LemonButton>
                            </div>
                        }
                    />
                )
            })}
            <div className="flex">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<img src={ICONS['google-calendar']} className="h-4 w-4" alt="" />}
                    disableClientSideRouting
                    loading={integrationsLoading}
                    to={api.integrations.authorizeUrl({
                        kind: 'google-calendar',
                        next: urls.settings('environment-customer-analytics'),
                    })}
                >
                    {calendarIntegrations.length ? 'Connect another calendar' : 'Connect Google Calendar'}
                </LemonButton>
            </div>
        </div>
    )
}
