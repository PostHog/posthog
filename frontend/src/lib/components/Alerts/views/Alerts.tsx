import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { alertIntervalDisplayLabel } from 'products/alerts/frontend/logic/alertIntervalHelpers'

import { AlertState } from '../../../../queries/schema/schema-general'
import { alertLogic } from '../alertLogic'
import { AlertsFiltersBar } from '../AlertsFiltersBar'
import { alertsLogic } from '../alertsLogic'
import { AlertType } from '../types'
import { EditAlertModal } from './EditAlertModal'
import { AlertStateIndicator } from './ManageAlertsModal'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

interface AlertsProps {
    alertId: AlertType['id'] | null
}

export function Alerts({ alertId }: AlertsProps): JSX.Element {
    const { push } = useActions(router)
    const logic = alertsLogic()
    const { loadAlerts } = useActions(logic)
    const { alertsSortedByState, alertsResponseLoading, pagination, alertsCount, isFiltering } = useValues(logic)

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
            render: (enabled: any) =>
                enabled ? <LemonTag type="success">ENABLED</LemonTag> : <LemonTag type="danger">DISABLED</LemonTag>,
        },
    ]

    const isEmpty = alertsCount === 0 && !alertsResponseLoading && !isFiltering
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
                    customHog={HedgehogMagnifyingGlass}
                    actionElementOverride={
                        <span className="italic">
                            To get started, visit a <Link to={urls.insights()}>trends insight</Link>, visit the
                            'Actions' in the sidebar and click 'Alerts'
                        </span>
                    }
                    mcpSurfaceKey="alerts.create"
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
