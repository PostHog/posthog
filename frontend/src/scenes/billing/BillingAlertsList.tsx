import { useActions, useValues } from 'kea'

import { IconBell, IconCreditCard, IconPlay, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag, Link } from '@posthog/lemon-ui'

import { AlertingListToolbar, AlertingTable } from 'lib/components/Alerting'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import type { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { BillingAlertDestinationPanel } from './BillingAlertDestination'
import { metricLabel, stateLabel, stateTagType, thresholdDescription } from './billingAlertDisplay'
import { BillingAlertEvents } from './BillingAlertEvents'
import { BillingAlertCreationView, billingAlertsLogic } from './billingAlertsLogic'
import type { BillingAlertConfiguration } from './billingAlertsLogic'

export function BillingAlertsList(): JSX.Element {
    const {
        alerts,
        alertsLoading,
        filteredAlerts,
        hiddenAlertCount,
        filters,
        eventsByAlert,
        eventsLoadFailedIds,
        alertsLoadFailed,
        checkingAlertId,
        updatingAlertIds,
    } = useValues(billingAlertsLogic)
    const {
        setFilters,
        resetFilters,
        setCreationView,
        updateAlert,
        deleteAlert,
        checkNow,
        loadEvents,
        openDestinationPanel,
    } = useActions(billingAlertsLogic)

    const columns: LemonTableColumns<BillingAlertConfiguration> = [
        {
            title: '',
            width: 0,
            render: function RenderIcon() {
                return <IconCreditCard className="text-2xl text-muted" />
            },
        },
        {
            title: 'Name',
            sticky: true,
            sorter: (a, b) =>
                (a.name ?? '').localeCompare(b.name ?? '', undefined, { sensitivity: 'base', numeric: true }),
            key: 'name',
            dataIndex: 'name',
            render: function RenderName(_, alert) {
                return (
                    <LemonTableLink
                        title={
                            <>
                                <span>{alert.name}</span>
                                <LemonTag size="small" type="muted" icon={<IconBell />}>
                                    Billing
                                </LemonTag>
                            </>
                        }
                        description={`${metricLabel(alert.metric)} alert: ${thresholdDescription(alert)}`}
                    />
                )
            },
        },
        createdByColumn() as LemonTableColumn<BillingAlertConfiguration, any>,
        updatedAtColumn() as LemonTableColumn<BillingAlertConfiguration, any>,
        {
            title: 'Last checked',
            width: 0,
            render: function RenderLastChecked(_, alert) {
                return alert.last_checked_at ? dayjs(alert.last_checked_at).fromNow() : 'N/A'
            },
        },
        {
            title: 'Status',
            key: 'enabled',
            sorter: (alert) => (alert.enabled ? 1 : -1),
            width: 0,
            render: function RenderStatus(_, alert) {
                return (
                    <LemonTag type={stateTagType(alert.state, alert.enabled)}>
                        {stateLabel(alert.state, alert.enabled)}
                    </LemonTag>
                )
            },
        },
        {
            width: 0,
            render: function RenderActions(_, alert) {
                const updating = updatingAlertIds.has(alert.id)
                return (
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: alert.enabled ? 'Pause' : 'Unpause',
                                        disabledReason: updating ? 'Saving' : undefined,
                                        onClick: () => updateAlert(alert, { enabled: !alert.enabled }),
                                    },
                                    {
                                        label: 'Check now',
                                        icon: <IconPlay />,
                                        disabledReason: checkingAlertId ? 'Another alert is checking' : undefined,
                                        onClick: () =>
                                            LemonDialog.open({
                                                title: 'Check billing alert now?',
                                                description:
                                                    'Manual checks use the same notification path as scheduled checks, so this can send notifications if the alert fires, resolves, or errors.',
                                                primaryButton: {
                                                    children: 'Check now',
                                                    icon: <IconPlay />,
                                                    onClick: () => checkNow(alert),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            }),
                                    },
                                    {
                                        label: 'Add destination',
                                        icon: <IconPlus />,
                                        onClick: () => openDestinationPanel(alert.id),
                                    },
                                    {
                                        label: 'Delete',
                                        status: 'danger' as const,
                                        disabledReason: updating ? 'Deleting' : undefined,
                                        onClick: () =>
                                            LemonDialog.open({
                                                title: 'Delete billing alert?',
                                                description: `This deletes "${alert.name}" and its destinations.`,
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => deleteAlert(alert),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            }),
                                    },
                                ]}
                            />
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4" data-attr="billing-alerts-view">
            <AlertingListToolbar
                searchValue={filters.search}
                onSearchChange={(search) => setFilters({ search })}
                createdByValue={filters.createdBy}
                onCreatedByChange={(user) => setFilters({ createdBy: user?.id ?? null })}
                showPaused={filters.showPaused}
                onShowPausedChange={(showPaused) => setFilters({ showPaused: !!showPaused })}
                extraControls={
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => setCreationView(BillingAlertCreationView.Wizard)}
                    >
                        New notification
                    </LemonButton>
                }
            />

            <AlertingTable
                dataSource={filteredAlerts}
                columns={columns}
                rowKey="id"
                nouns={['billing alert', 'billing alerts']}
                loading={alertsLoading}
                emptyState={
                    alertsLoadFailed ? (
                        "Couldn't load billing alerts."
                    ) : alerts.length === 0 && !alertsLoading ? (
                        'No billing alerts found'
                    ) : (
                        <>
                            No billing alerts matching filters. <Link onClick={resetFilters}>Clear filters</Link>
                        </>
                    )
                }
                footer={
                    hiddenAlertCount > 0 ? (
                        <div className="p-3 text-secondary">
                            {hiddenAlertCount} hidden.{' '}
                            <Link
                                onClick={() => {
                                    resetFilters()
                                    setFilters({ showPaused: true })
                                }}
                            >
                                Show all
                            </Link>
                        </div>
                    ) : null
                }
                data-attr="billing-alerts-table"
                pagination={{ pageSize: 30 }}
                expandable={{
                    expandedRowRender: (alert) => (
                        <BillingAlertEvents
                            events={eventsByAlert[alert.id]}
                            failed={eventsLoadFailedIds.has(alert.id)}
                        />
                    ),
                    onRowExpand: (alert) => loadEvents(alert.id),
                }}
            />

            <BillingAlertDestinationPanel />
        </div>
    )
}
