import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import type { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { AlertState } from '~/queries/schema/schema-general'

import { AlertStateIndicator } from '../components/AlertDefinition'
import { AlertsFiltersBar } from '../components/AlertsFiltersBar'
import { alertIntervalDisplayLabel } from '../logic/alertIntervalHelpers'
import { alertLogic } from '../logic/alertLogic'
import { alertNotificationLogic } from '../logic/alertNotificationLogic'
import { alertsLogic } from '../logic/alertsLogic'
import { AlertType } from '../types'
import { EditAlertModal } from './EditAlertModal'
import { AlertNotFoundModal } from './EditAlertModal/AlertNotFoundModal'

interface InsightAlertsProps {
    alertId: AlertType['id'] | null
}

interface AlertRowMenuProps {
    alert: AlertType
    destinationCount: number
    deleting: boolean
    onDelete: () => void
}

function AlertRowMenu({ alert, destinationCount, deleting, onDelete }: AlertRowMenuProps): JSX.Element {
    const notificationLogic = alertNotificationLogic({ alertId: alert.id, loadDestinations: false })
    const { testDeliveryResultLoading } = useValues(notificationLogic)
    const { sendTestDelivery } = useActions(notificationLogic)

    const canTestDelivery = alert.subscribed_users.some((user) => Boolean(user.email)) || destinationCount > 0
    const menuItems: LemonMenuItems = [
        canTestDelivery && {
            label: 'Test delivery',
            'data-attr': 'insight-alert-row-send-test',
            disabledReason: testDeliveryResultLoading ? 'Sending test delivery…' : null,
            onClick: sendTestDelivery,
        },
        {
            label: 'Delete',
            status: 'danger' as const,
            'data-attr': 'insight-alert-row-delete',
            disabledReason: deleting ? 'Deleting…' : null,
            onClick: onDelete,
        },
    ]

    return (
        <LemonMenu items={menuItems} placement="bottom-end">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconEllipsis />}
                aria-label={`More options for ${alert.name}`}
            />
        </LemonMenu>
    )
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
        isFiltering,
        togglingAlertIds,
        alertDestinationCounts,
    } = useValues(logic)

    const { alert, alertLoading } = useValues(alertLogic({ alertId }))

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
                return <AlertStateIndicator alert={alert} />
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
                <AlertRowMenu
                    alert={alert}
                    destinationCount={alertDestinationCounts[alert.id] ?? 0}
                    deleting={deletingAlertIds.has(alert.id)}
                    onDelete={() => {
                        LemonDialog.open({
                            title: `Delete "${alert.name}"?`,
                            description: 'This alert will be permanently deleted. This action cannot be undone.',
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
                />
            ),
        },
    ]

    const alertForEditModal = alert ?? alertsSortedByState.find((candidate) => candidate.id === alertId)
    return (
        <>
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

            {alertId && !alertForEditModal && !alertLoading && (
                <AlertNotFoundModal isOpen onClose={() => push(urls.alerts())} />
            )}

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
                    ) : (
                        <div className="py-8 text-center text-secondary">
                            Insight alerts start on the insight. Open a <Link to={urls.insights()}>saved insight</Link>,
                            then pick Alerts in its actions sidebar.
                        </div>
                    )
                }
            />
        </>
    )
}
