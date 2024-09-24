import { TZLabel } from '@posthog/apps-common'
import { IconCheck } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { AlertState, AlertType } from '../../../../queries/schema'
import { alertsLogic } from '../alertsLogic'
import { EditAlertModal } from './EditAlertModal'
import { AlertStateIndicator } from './ManageAlertsModal'

interface AlertsProps {
    alertId: AlertType['id'] | null
}

export function Alerts({ alertId }: AlertsProps): JSX.Element {
    const { push } = useActions(router)
    const logic = alertsLogic()
    const { loadAlerts } = useActions(logic)

    const { alertsSortedByState, alertsLoading } = useValues(logic)

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
                                <>
                                    <div>{alert.enabled ? <AlertStateIndicator alert={alert} /> : null}</div>
                                    {name}
                                </>
                            }
                        />
                    </>
                )
            },
        },
        {
            title: 'Last checked',
            sorter: true,
            dataIndex: 'last_checked_at',
            render: function renderLastChecked(last_checked_at: any) {
                return <div className="whitespace-nowrap">{last_checked_at && <TZLabel time={last_checked_at} />}</div>
            },
        },
        {
            title: 'Last notified',
            sorter: true,
            dataIndex: 'last_notified_at',
            render: function renderLastModified(last_notified_at: any) {
                return (
                    <div className="whitespace-nowrap">{last_notified_at && <TZLabel time={last_notified_at} />}</div>
                )
            },
        },
        createdAtColumn() as LemonTableColumn<AlertType, keyof AlertType | undefined>,
        createdByColumn() as LemonTableColumn<AlertType, keyof AlertType | undefined>,
        {
            title: 'Enabled',
            dataIndex: 'enabled',
            key: 'enabled',
            render: (enabled: any) => (enabled ? <IconCheck /> : null),
        },
    ]

    // TODO: add info here to sign up for alerts early access
    return (
        <>
            {alertId && (
                <EditAlertModal
                    onClose={() => push(urls.alerts())}
                    isOpen
                    alertId={alertId}
                    onEditSuccess={loadAlerts}
                />
            )}

            <LemonTable
                loading={alertsLoading}
                columns={columns}
                dataSource={alertsSortedByState}
                noSortingCancellation
                rowKey="id"
                loadingSkeletonRows={5}
                nouns={['alert', 'alerts']}
                rowClassName={(alert) => (alert.state === AlertState.NOT_FIRING ? null : 'highlighted')}
            />
        </>
    )
}
