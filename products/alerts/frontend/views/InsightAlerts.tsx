import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import { AlertState, ProductKey } from '~/queries/schema/schema-general'

import { AlertStateIndicator } from '../components/AlertDefinition'
import { AlertsFiltersBar } from '../components/AlertsFiltersBar'
import { alertIntervalDisplayLabel } from '../logic/alertIntervalHelpers'
import { alertLogic } from '../logic/alertLogic'
import { alertsLogic } from '../logic/alertsLogic'
import { AlertType } from '../types'
import { EditAlertModal } from './EditAlertModal'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

interface InsightAlertsProps {
    alertId: AlertType['id'] | null
}

export function InsightAlerts({ alertId }: InsightAlertsProps): JSX.Element {
    const { push } = useActions(router)
    const logic = alertsLogic()
    const { deleteAlert, loadAlerts, toggleAlertEnabled } = useActions(logic)
    const {
        alertsSortedByState,
        alertsResponseLoading,
        deletingAlertIds,
        pagination,
        alertsCount,
        isFiltering,
        togglingAlertIds,
    } = useValues(logic)

    const { alert } = useValues(alertLogic({ alertId }))

    const columns: LemonTableColumns<AlertType> = [
        {
            key: 'id',
            width: 32,
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: any, alert) {
                return (
                    <>
                        <LemonTableLink
                            to={urls.alert(alert.id)}
                            className={alert.enabled ? '' : 'text-muted'}
                            title={
                                <div className="flex flex-row gap-3 items-center">
                                    <div>{name}</div>
                                </div>
                            }
                        />
                    </>
                )
            },
        },
        {
            title: 'Status',
            dataIndex: 'state',
            render: function renderStateIndicator(_, alert: AlertType) {
                return alert.enabled ? <AlertStateIndicator alert={alert} /> : null
            },
        },
        {
            title: 'Interval',
            dataIndex: 'calculation_interval',
            key: 'calculation_interval',
            render: function renderInterval(_, alert: AlertType) {
                return <div className="whitespace-nowrap">{alertIntervalDisplayLabel(alert.calculation_interval)}</div>
            },
        },
        {
            title: 'Last checked',
            sorter: true,
            defaultSortOrder: -1,
            dataIndex: 'last_checked_at',
            render: function renderLastChecked(_, alert: AlertType) {
                return (
                    <div className="whitespace-nowrap">
                        {alert.last_checked_at ? (
                            <TZLabel time={alert.last_checked_at} />
                        ) : (
                            <span className="text-muted">N/A</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Last notified',
            sorter: true,
            defaultSortOrder: -1,
            dataIndex: 'last_notified_at',
            render: function renderLastModified(_, alert: AlertType) {
                return (
                    <div className="whitespace-nowrap">
                        {alert.last_notified_at ? (
                            <TZLabel time={alert.last_notified_at} />
                        ) : (
                            <span className="text-muted">N/A</span>
                        )}
                    </div>
                )
            },
        },
        createdByColumn() as LemonTableColumn<AlertType, keyof AlertType | undefined>,
        {
            title: 'Insight',
            dataIndex: 'insight',
            key: 'insight',
            render: function renderInsightLink(insight: any) {
                return (
                    <LemonTableLink
                        to={urls.insightView(insight.short_id)}
                        title={
                            <Tooltip title={insight.name}>
                                <div>{insight.name || insight.derived_name}</div>
                            </Tooltip>
                        }
                    />
                )
            },
        },
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            key: 'enabled',
            render: (_, alert) => (
                <LemonSwitch
                    checked={alert.enabled}
                    onChange={() => toggleAlertEnabled(alert)}
                    loading={togglingAlertIds.has(alert.id)}
                    aria-label={`${alert.enabled ? 'Disable' : 'Enable'} ${alert.name}`}
                    data-attr="insight-alert-row-toggle"
                />
            ),
        },
        {
            title: '',
            render: (_, alert) => (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconEllipsis />}
                                aria-label={`More options for ${alert.name}`}
                            />
                        }
                    />
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem
                            variant="destructive"
                            data-attr="insight-alert-row-delete"
                            disabled={deletingAlertIds.has(alert.id)}
                            onClick={() => {
                                LemonDialog.open({
                                    title: `Delete "${alert.name}"?`,
                                    description:
                                        'This alert will be permanently deleted. This action cannot be undone.',
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        status: 'danger',
                                        onClick: () => deleteAlert(alert),
                                        'data-attr': 'insight-alert-delete-confirm',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }}
                        >
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ),
        },
    ]

    const isEmpty = alertsCount === 0 && !alertsResponseLoading && !isFiltering
    const alertForEditModal = alert ?? alertsSortedByState.find((candidate) => candidate.id === alertId)
    return (
        <>
            {isEmpty && (
                <ProductIntroduction
                    productName="Alerts"
                    productKey={ProductKey.ALERTS}
                    thingName="alert"
                    description="Alerts enable you to monitor your insight and notify you when certain conditions are met."
                    isEmpty
                    customHog={HedgehogMagnifyingGlass}
                    actionElementOverride={
                        <span className="italic">
                            To get started, open a <Link to={urls.insights()}>saved insight</Link>, then select Alerts
                            from the Actions sidebar.
                        </span>
                    }
                    mcpSurfaceKey="alerts.create"
                />
            )}

            {alertForEditModal && (
                <EditAlertModal
                    onClose={() => push(urls.alerts())}
                    isOpen
                    alert={alertForEditModal}
                    useAlertCheckPreview
                    onEditSuccess={() => {
                        loadAlerts()
                        push(urls.alerts())
                    }}
                />
            )}

            {isEmpty ? null : (
                <>
                    <AlertsFiltersBar />
                    <LemonTable
                        loading={alertsResponseLoading}
                        columns={columns}
                        dataSource={alertsSortedByState}
                        noSortingCancellation
                        rowKey="id"
                        loadingSkeletonRows={5}
                        nouns={['alert', 'alerts']}
                        pagination={pagination}
                        rowClassName={(alert) => (alert.state === AlertState.NOT_FIRING ? null : 'highlighted')}
                        emptyState={
                            isFiltering ? (
                                <div className="py-8 text-center text-secondary">No alerts match your filters</div>
                            ) : undefined
                        }
                    />
                </>
            )}
        </>
    )
}
