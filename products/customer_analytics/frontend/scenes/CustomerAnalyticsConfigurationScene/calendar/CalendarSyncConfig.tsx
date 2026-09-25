import { useActions, useValues } from 'kea'

import { IconRefresh, IconRewind, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { ICONS } from 'lib/integrations/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { CalendarSyncBackfillModal } from './CalendarSyncBackfillModal'
import { calendarSyncLogic } from './calendarSyncLogic'

const GMAIL_READONLY_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'

export function CalendarSyncConfig(): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)
    const {
        statusByIntegrationId,
        triggeringIntegrationIds,
        backfillIntegrationId,
        backfillStartDate,
        backfillEndDate,
        backfillDateError,
        backfillSubmitting,
        savingIntervalIds,
    } = useValues(calendarSyncLogic)
    const {
        syncNow,
        openBackfill,
        closeBackfill,
        setBackfillStartDate,
        setBackfillEndDate,
        submitBackfill,
        saveInterval,
    } = useActions(calendarSyncLogic)
    const { user } = useValues(userLogic)
    const adminRestrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const calendarIntegrations = integrations?.filter((integration) => integration.kind === 'google-calendar') ?? []
    const managementRestrictedReason = (createdById?: number): string | null =>
        createdById === user?.id ? null : adminRestrictedReason
    const needsEmailPermission = calendarIntegrations.some(
        (integration) =>
            !managementRestrictedReason(integration.created_by?.id) &&
            !String(integration.config?.scope ?? '')
                .split(' ')
                .includes(GMAIL_READONLY_SCOPE)
    )
    const authorizeUrl = api.integrations.authorizeUrl({
        kind: 'google-calendar',
        next: `${urls.customerAnalyticsConfiguration('customer-analytics-calendar-sync')}#selectedSetting=customer-analytics-calendar-sync`,
    })

    return (
        <div className="flex flex-col gap-4">
            {needsEmailPermission && (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Reconnect Google account',
                        to: authorizeUrl,
                        disableClientSideRouting: true,
                        'data-attr': 'reconnect-google-account',
                    }}
                >
                    Reconnect your Google account to let PostHog sync customer email as well as calendar meetings.
                </LemonBanner>
            )}
            <div className="flex">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<img src={ICONS['google-calendar']} className="h-4 w-4" alt="" />}
                    disableClientSideRouting
                    loading={integrationsLoading}
                    to={authorizeUrl}
                    data-attr="calendar-sync-connect-google-account"
                >
                    {calendarIntegrations.length ? 'Connect another Google account' : 'Connect Google account'}
                </LemonButton>
            </div>
            {calendarIntegrations.map((integration) => {
                const syncStatus = statusByIntegrationId[integration.id]
                const isSyncing = !!syncStatus?.is_syncing || triggeringIntegrationIds.includes(integration.id)
                const restrictedReason = managementRestrictedReason(integration.created_by?.id)
                const hasGmailScope = String(integration.config?.scope ?? '')
                    .split(' ')
                    .includes(GMAIL_READONLY_SCOPE)
                const backfillDisabledReason = backfillSubmitting
                    ? 'Another backfill request is starting'
                    : isSyncing
                      ? 'A sync is already running'
                      : (adminRestrictedReason ??
                        (!hasGmailScope ? 'Reconnect this Google account before you backfill email' : null))
                return (
                    <IntegrationView
                        key={integration.id}
                        integration={integration}
                        // A custom suffix replaces IntegrationView's built-in Disconnect button, so it returns here.
                        suffix={
                            <div className="flex flex-row flex-wrap items-center justify-end gap-2">
                                {!adminRestrictedReason && (
                                    <label className="flex items-center gap-2 text-xs whitespace-nowrap">
                                        Sync every
                                        <LemonSelect<number>
                                            data-attr={`google-account-sync-interval-${integration.id}`}
                                            value={syncStatus?.sync_interval_minutes ?? 60}
                                            options={[
                                                { value: 5, label: '5 minutes' },
                                                { value: 15, label: '15 minutes' },
                                                { value: 30, label: '30 minutes' },
                                                { value: 60, label: '1 hour' },
                                            ]}
                                            disabledReason={
                                                savingIntervalIds.includes(integration.id) ? 'Saving...' : undefined
                                            }
                                            onChange={(value) => saveInterval(integration.id, value)}
                                        />
                                    </label>
                                )}
                                <span className="text-xs text-secondary whitespace-nowrap">
                                    {isSyncing ? (
                                        'Syncing Google account...'
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
                                    icon={<IconRewind />}
                                    disabledReason={backfillDisabledReason ?? undefined}
                                    onClick={() => openBackfill(integration.id)}
                                    data-attr="google-account-backfill-open"
                                >
                                    Backfill
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
            <CalendarSyncBackfillModal
                isOpen={backfillIntegrationId !== null}
                startDate={backfillStartDate}
                endDate={backfillEndDate}
                dateError={backfillDateError}
                isSubmitting={backfillSubmitting}
                onStartDateChange={setBackfillStartDate}
                onEndDateChange={setBackfillEndDate}
                onSubmit={() => {
                    if (backfillIntegrationId !== null && backfillStartDate && backfillEndDate) {
                        submitBackfill(backfillIntegrationId, backfillStartDate, backfillEndDate)
                    }
                }}
                onClose={closeBackfill}
            />
        </div>
    )
}
