import { useActions, useValues } from 'kea'

import { IconMessage, IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { createdByColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import {
    DestinationTypeEnumApi,
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationSourceKindEnumApi,
    WarehouseAlertGroupByEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'
import { configurationStatus } from 'products/alerts_platform/frontend/platformAlertFormat'
import { PlatformAlertStatusTag } from 'products/alerts_platform/frontend/PlatformAlertStatusTag'

import { alertGroupBy, emailsProjectMembers, watchedIds } from './warehouseAlertConfig'
import { WarehouseAlertModal } from './WarehouseAlertModal'
import { WarehouseAlertEntry, warehouseAlertModalLogic } from './warehouseAlertModalLogic'
import { WarehouseAlertsLogicProps, warehouseAlertsLogic } from './warehouseAlertsLogic'

const DESTINATION_ICON_SRC: Partial<Record<DestinationTypeEnumApi, string>> = {
    [DestinationTypeEnumApi.Slack]: '/static/services/slack.png',
    [DestinationTypeEnumApi.Teams]: '/static/services/microsoft-teams.png',
    [DestinationTypeEnumApi.Discord]: '/static/services/discord.png',
    [DestinationTypeEnumApi.Pagerduty]: '/static/services/pagerduty.png',
    [DestinationTypeEnumApi.Webhook]: '/static/services/webhook.svg',
    [DestinationTypeEnumApi.IncidentIo]: '/static/services/incident_io.png',
}

const DESTINATION_LABEL: Record<DestinationTypeEnumApi, string> = {
    [DestinationTypeEnumApi.Slack]: 'Slack',
    [DestinationTypeEnumApi.Teams]: 'Microsoft Teams',
    [DestinationTypeEnumApi.Discord]: 'Discord',
    [DestinationTypeEnumApi.Pagerduty]: 'PagerDuty',
    [DestinationTypeEnumApi.Webhook]: 'Webhook',
    [DestinationTypeEnumApi.IncidentIo]: 'incident.io',
    [DestinationTypeEnumApi.Email]: 'Email',
    [DestinationTypeEnumApi.InApp]: 'In-app notification',
}

// The alerts platform writes one app metric per notification it sends, under the alert configuration's id.
const ALERT_APP_SOURCE = 'alert'
const ALERT_METRIC_LABELS: Record<string, string> = { success: 'Sent', failure: 'Failed' }

// Past this many logos the row grows too wide, so the rest collapse into a "+N" chip.
const MAX_STACKED_ICONS = 3

function DestinationTypeIcon({ type }: { type: DestinationTypeEnumApi }): JSX.Element {
    const src = DESTINATION_ICON_SRC[type]
    // Email and in-app notifications have no logo, so they share one generic icon.
    return src ? (
        <HogFunctionIcon src={src} size="small" />
    ) : (
        <span className="flex items-center justify-center w-[30px] h-[30px] text-2xl text-secondary">
            <IconMessage />
        </span>
    )
}

function AlertDestinationIcons({ alert }: { alert: PlatformAlertConfigurationApi }): JSX.Element | null {
    const types = Array.from(new Set(alert.destination_types))
    if (types.length === 0) {
        return null
    }
    const shown = types.slice(0, MAX_STACKED_ICONS)
    const hidden = types.length - shown.length
    return (
        <Tooltip title={types.map((type) => DESTINATION_LABEL[type] ?? type).join(', ')}>
            <span className="flex items-center gap-1">
                {/* Reversed so the first destination comes last in the DOM and paints on top of the others. */}
                <span className="flex flex-row-reverse items-center">
                    {[...shown].reverse().map((type, index) => (
                        <span
                            key={type}
                            className={`relative rounded bg-surface-primary ring-2 ring-surface-primary${
                                index < shown.length - 1 ? ' -ml-4' : ''
                            }`}
                        >
                            <DestinationTypeIcon type={type} />
                        </span>
                    ))}
                </span>
                {hidden > 0 ? (
                    <span className="flex items-center justify-center min-w-6 h-6 px-1 rounded-full bg-fill-highlight-100 text-xs font-semibold">
                        +{hidden}
                    </span>
                ) : null}
            </span>
        </Tooltip>
    )
}

export interface WarehouseAlertsSectionProps extends WarehouseAlertsLogicProps {
    /** Where the section sits, recorded on the events it sends. */
    entry: WarehouseAlertEntry
}

export function WarehouseAlertsSection({ entry, ...logicProps }: WarehouseAlertsSectionProps): JSX.Element {
    const {
        alerts,
        alertsLoading,
        alertsFailed,
        alertsUnavailable,
        deletingAlertId,
        togglingAlertId,
        targetLabels,
        filters,
        filteredAlerts,
        hiddenAlertCount,
    } = useValues(warehouseAlertsLogic(logicProps))
    const { loadAlerts, deleteAlert, toggleAlertEnabled, setFilters, resetFilters } = useActions(
        warehouseAlertsLogic(logicProps)
    )
    const { openForCreate, openForEdit } = useActions(warehouseAlertModalLogic(logicProps))

    const isSourceAlert = logicProps.kind === PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource
    const noun = isSourceAlert ? 'source' : 'destination'
    const createTargets = logicProps.targetId ? [logicProps.targetId] : []

    const describeWatches = (alert: PlatformAlertConfigurationApi): string => {
        const ids = watchedIds(alert)
        if (ids.length === 0) {
            return `All ${noun}s`
        }
        // A deleted source or destination has no label any more, so it reads as its id.
        return ids.map((id) => targetLabels[id] ?? id).join(', ')
    }

    const columns: LemonTableColumns<PlatformAlertConfigurationApi> = [
        {
            title: '',
            width: 0,
            render: (_, alert) => <AlertDestinationIcons alert={alert} />,
        },
        {
            title: 'Name',
            key: 'name',
            sticky: true,
            sorter: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true }),
            render: (_, alert) => (
                <LemonTableLink
                    title={
                        <>
                            <Link subtle onClick={() => openForEdit(entry, alert)} data-attr="warehouse-alert-row-open">
                                {alert.name}
                            </Link>
                            <LemonTag size="small" type="muted">
                                {isSourceAlert ? 'Source' : 'Destination'}
                            </LemonTag>
                        </>
                    }
                    description={describeWatches(alert)}
                    truncateDescription
                />
            ),
        },
        ...(isSourceAlert
            ? [
                  {
                      title: 'One alert',
                      key: 'group_by',
                      render: (_: unknown, alert: PlatformAlertConfigurationApi) =>
                          alertGroupBy(alert) === WarehouseAlertGroupByEnumApi.Schema ? 'Per table' : 'Per source',
                  } as LemonTableColumn<PlatformAlertConfigurationApi, any>,
              ]
            : []),
        {
            title: 'Emails members',
            key: 'email',
            render: (_, alert) => (emailsProjectMembers(alert) ? 'Yes' : 'No'),
        },
        createdByColumn() as unknown as LemonTableColumn<PlatformAlertConfigurationApi, any>,
        updatedAtColumn() as LemonTableColumn<PlatformAlertConfigurationApi, any>,
        {
            title: 'Last 7 days',
            tooltip: 'Notifications sent and failed each day',
            width: 0,
            render: (_, alert) => (
                <AppMetricsSparkline
                    logicKey={`warehouse-alert-sparkline-${alert.id}`}
                    metricLabels={ALERT_METRIC_LABELS}
                    forceParams={{
                        appSource: ALERT_APP_SOURCE,
                        appSourceId: alert.id,
                        metricKind: ['success', 'failure'],
                        breakdownBy: 'metric_kind',
                        interval: 'day',
                        dateFrom: '-7d',
                    }}
                />
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 0,
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
            render: (_, alert) => <PlatformAlertStatusTag status={configurationStatus(alert)} />,
        },
        {
            width: 0,
            render: (_, alert) => (
                <More
                    overlay={
                        <LemonMenuOverlay
                            items={[
                                {
                                    label: 'Edit',
                                    onClick: () => openForEdit(entry, alert),
                                    'data-attr': 'warehouse-alert-row-edit',
                                },
                                {
                                    label: alert.enabled ? 'Pause' : 'Resume',
                                    onClick: () => toggleAlertEnabled(alert, !alert.enabled),
                                    disabledReason: togglingAlertId === alert.id ? 'Updating this alert' : undefined,
                                    'data-attr': 'warehouse-alert-row-toggle',
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger' as const,
                                    onClick: () => deleteAlert(alert),
                                    disabledReason: deletingAlertId === alert.id ? 'Deleting this alert' : undefined,
                                    'data-attr': 'warehouse-alert-row-delete',
                                },
                            ]}
                        />
                    }
                />
            ),
        },
    ]

    const hasAlerts = (alerts ?? []).length > 0

    return (
        <SceneSection
            title="Alerts"
            description={
                isSourceAlert
                    ? 'Get notified by email, Slack, PagerDuty or a webhook when a source fails to sync.'
                    : 'Get notified by email, Slack, PagerDuty or a webhook when a destination fails to receive synced rows.'
            }
        >
            {alertsUnavailable ? (
                <LemonBanner type="info">Alerts aren't available for this project yet.</LemonBanner>
            ) : alertsFailed ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadAlerts(),
                        loading: alertsLoading,
                        'data-attr': 'warehouse-alerts-retry',
                    }}
                >
                    Couldn't load alerts. Try again in a moment.
                </LemonBanner>
            ) : (
                <div className="flex flex-col gap-4">
                    <div className="flex flex-wrap gap-2 items-center">
                        <LemonInput
                            type="search"
                            placeholder="Search..."
                            value={filters.search}
                            onChange={(search) => setFilters({ search })}
                        />
                        <div className="flex-1" />
                        <div className="flex flex-col xl:flex-row items-center gap-0.5 xl:gap-2 shrink-0">
                            <span className="text-xs xl:text-sm">Created by:</span>
                            <MemberSelect
                                value={filters.createdBy}
                                onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                            />
                        </div>
                        <LemonCheckbox
                            label="Show paused"
                            bordered
                            size="small"
                            checked={filters.showPaused}
                            onChange={(showPaused) => setFilters({ showPaused: !!showPaused })}
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlusSmall />}
                            onClick={() => openForCreate(entry, createTargets)}
                            data-attr="warehouse-alert-new"
                        >
                            New alert
                        </LemonButton>
                    </div>
                    <LemonTable
                        dataSource={filteredAlerts}
                        columns={columns}
                        size="small"
                        loading={alertsLoading || alerts === null}
                        rowKey="id"
                        nouns={['alert', 'alerts']}
                        emptyState={
                            hasAlerts ? (
                                <>
                                    No alerts matching filters.{' '}
                                    <Link onClick={() => resetFilters()}>Clear filters</Link>
                                </>
                            ) : logicProps.targetId ? (
                                `No alerts watch this ${noun} yet.`
                            ) : (
                                `No ${noun} alerts yet. Create one to hear about failures.`
                            )
                        }
                        footer={
                            hiddenAlertCount > 0 && (
                                <div className="p-3 text-secondary">
                                    {hiddenAlertCount} paused.{' '}
                                    <Link onClick={() => setFilters({ showPaused: true })}>Show all</Link>
                                </div>
                            )
                        }
                    />
                </div>
            )}
            <WarehouseAlertModal {...logicProps} />
        </SceneSection>
    )
}
