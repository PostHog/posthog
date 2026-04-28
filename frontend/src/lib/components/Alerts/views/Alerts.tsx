import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { DetectiveHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

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

    const { featureFlags } = useValues(featureFlagLogic)
    const alertsHistoryChartEnabled = !!featureFlags[FEATURE_FLAGS.ALERTS_HISTORY_CHART]
    const { alert } = useValues(alertLogic({ alertId, historyChartEnabled: alertsHistoryChartEnabled }))

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
            render: (enabled: any) =>
                enabled ? <LemonTag type="success">ENABLED</LemonTag> : <LemonTag type="danger">DISABLED</LemonTag>,
        },
    ]

    const isEmpty = alertsSortedByState.length === 0 && !alertsLoading
    // TODO: add info here to sign up for alerts early access
    return (
        <>
            {isEmpty && (
                <ProductIntroduction
                    productName="Alerts"
                    productKey={ProductKey.ALERTS}
                    thingName="alert"
                    description="Alerts enable you to monitor your insight and notify you when certain conditions are met."
                    isEmpty
                    customHog={DetectiveHog}
                    actionElementOverride={
                        <span className="italic">
                            To get started, visit a <Link to={urls.insights()}>trends insight</Link>, visit the
                            'Actions' in the sidebar and click 'Alerts'
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

            {isEmpty ? null : (
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
            )}
        </>
    )
}
