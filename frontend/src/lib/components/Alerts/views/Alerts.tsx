import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { DetectiveHog } from 'lib/components/hedgehogs'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { AlertState } from '../../../../queries/schema/schema-general'
import { alertLogic } from '../alertLogic'
import { alertsLogic } from '../alertsLogic'
import { AlertType } from '../types'
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
            render: (enabled: any) =>
                enabled ? <LemonTag type="success">ENABLED</LemonTag> : <LemonTag type="danger">DISABLED</LemonTag>,
        },
    ]

    // TODO: add info here to sign up for alerts early access
    return (
        <>
            {alertsSortedByState.length === 0 && !alertsLoading && (
                <ProductIntroduction
                    productName="Alerts"
                    productKey={ProductKey.ALERTS}
                    thingName="alert"
                    description="Alerts enable you to monitor your insight and notify you when certain conditions are met. Please note that alerts are in alpha and may not be fully reliable."
                    // TODO: update docs link when ready
                    // docsURL="https://posthog.com/docs/data/annotations"
                    isEmpty={alertsSortedByState.length === 0 && !alertsLoading}
                    customHog={DetectiveHog}
                    actionElementOverride={
                        <span className="italic">
                            To get started, visit a trends insight, expand options in the header and click 'Manage
                            Alerts'
                        </span>
                    }
                />
            )}

            {alert && (
                <EditAlertModal
                    onClose={() => push(urls.alerts())}
                    isOpen
                    alertId={alert.id}
                    insightShortId={alert.insight.short_id}
                    insightId={alert.insight.id}
                    insightLogicProps={{ dashboardItemId: alert.insight.short_id }}
                    onEditSuccess={() => {
                        loadAlerts()
                        push(urls.alerts())
                    }}
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
