import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSegmentedButton, LemonSkeleton, LemonTable, SpinnerOverlay } from '@posthog/lemon-ui'
import type { LemonTableColumn } from '@posthog/lemon-ui'

import { AlertHistoryChart } from 'lib/components/Alerts/views/AlertHistoryChart'
import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { formatDate } from 'lib/utils'

import { alertLogic, CHART_CHECKS_LIMIT, TABLE_CHECKS_PAGE_SIZE } from '../alertLogic'
import type { AlertCheck, AlertType } from '../types'

/** Placeholder while alert detail (including check history) is loading; avoids an empty gap before `AlertHistorySection` mounts. */
export function AlertHistorySectionSkeleton({ showChartArea = true }: { showChartArea?: boolean }): JSX.Element {
    return (
        <div className="mt-10 space-y-2" aria-busy="true" aria-label="Loading alert history">
            <div className="flex flex-row gap-2 items-center">
                <LemonSkeleton className="h-4 w-36" />
                <LemonSkeleton className="h-6 w-28" />
            </div>
            {showChartArea ? <LemonSkeleton className="h-8 w-44" /> : null}
            {showChartArea ? (
                <LemonSkeleton className="h-56 w-full min-h-56" />
            ) : (
                <LemonSkeleton className="h-72 w-full min-h-72" />
            )}
            {showChartArea ? <LemonSkeleton className="h-3 w-full max-w-xl" /> : null}
        </div>
    )
}

/** Check history in the alert modal: status, empty state, chart/table toggle (when enabled), and paginated table. */
export function AlertHistorySection({ alertId }: { alertId: AlertType['id'] }): JSX.Element | null {
    const historyChartEnabled = useFeatureFlag('ALERTS_HISTORY_CHART')
    const logic = alertLogic({ alertId, historyChartEnabled })
    const {
        alert,
        alertLoading,
        alertHistoryView,
        checksHistoryTablePage,
        alertHistoryChartSeries,
        alertHistoryChartSeriesName,
        alertHistoryUsesAnomalyScores,
        alertHistoryHasHistory,
        alertHistoryHasChartableHistory,
        alertHistoryChecksSortedDesc,
        alertHistoryTableEntryCount,
        alertHistoryIsAnomalyDetection,
    } = useValues(logic)
    const { selectAlertHistoryView, alertHistoryTablePageForward, alertHistoryTablePageBackward } = useActions(logic)

    const checkHistoryColumns = useMemo((): LemonTableColumn<AlertCheck, keyof AlertCheck | undefined>[] => {
        const columns: LemonTableColumn<AlertCheck, keyof AlertCheck | undefined>[] = [
            {
                title: 'Status',
                key: 'state',
                render: (_value, check) => check.state,
            },
            {
                title: 'Time',
                key: 'created_at',
                align: 'right',
                render: (_value, check) => <TZLabel time={check.created_at} />,
            },
            {
                title: 'Value',
                key: 'calculated_value',
                align: 'right',
                render: (_value, check) => check.calculated_value ?? '—',
            },
        ]
        if (alertHistoryIsAnomalyDetection) {
            columns.push({
                title: 'Score',
                align: 'right',
                render: (_value, check) => {
                    const scores = check.anomaly_scores
                    const lastScore = scores?.length ? scores[scores.length - 1] : null
                    return lastScore != null ? lastScore.toFixed(3) : '—'
                },
            })
        }
        columns.push({
            title: 'Targets notified',
            key: 'targets_notified',
            align: 'right',
            render: (_value, check) => (check.targets_notified ? 'Yes' : 'No'),
        })
        return columns
    }, [alertHistoryIsAnomalyDetection])

    if (!alert) {
        return null
    }

    const checksTotal = alert.checks_total

    return (
        <div className="mt-10 space-y-2">
            <div className="flex flex-row gap-2 items-center">
                <h3 className="m-0">Current status: </h3>
                <AlertStateIndicator alert={alert} />
                <h3 className="m-0">
                    {alert.snoozed_until && ` until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}
                </h3>
            </div>
            {!alertHistoryHasHistory ? (
                <div
                    className="flex min-h-56 items-center justify-center bg-bg-surface-primary border border-primary rounded"
                    data-attr="alert-check-history-empty"
                >
                    <EmptyMessage
                        title="No checks yet"
                        description="Check history will appear here after this alert runs."
                    />
                </div>
            ) : (
                <>
                    {alertHistoryHasChartableHistory ? (
                        <LemonSegmentedButton
                            size="small"
                            value={alertHistoryView}
                            onChange={(v) => selectAlertHistoryView(v)}
                            options={[
                                { value: 'chart', label: 'Chart' },
                                { value: 'table', label: 'Table' },
                            ]}
                        />
                    ) : null}
                    {historyChartEnabled && alertHistoryView === 'chart' && alertHistoryHasChartableHistory ? (
                        <div className="relative">
                            {alertLoading ? <SpinnerOverlay /> : null}
                            <AlertHistoryChart
                                points={alertHistoryChartSeries}
                                valueLabel={alertHistoryChartSeriesName}
                                alert={alert}
                                chartPlotsAnomalyScore={alertHistoryUsesAnomalyScores}
                                historyLimit={CHART_CHECKS_LIMIT}
                                checksTotal={checksTotal}
                            />
                        </div>
                    ) : (
                        <div className="h-72 max-h-72 shrink-0 overflow-hidden">
                            <LemonTable
                                dataSource={alertHistoryChecksSortedDesc}
                                columns={checkHistoryColumns}
                                rowKey="id"
                                size="small"
                                embedded
                                uppercaseHeader={false}
                                allowContentScroll
                                loading={alertLoading}
                                className="h-full min-h-0 !flex-none"
                                nouns={['check', 'checks']}
                                pagination={{
                                    controlled: true,
                                    hideOnSinglePage: false,
                                    currentPage: checksHistoryTablePage,
                                    pageSize: TABLE_CHECKS_PAGE_SIZE,
                                    entryCount: alertHistoryTableEntryCount,
                                    onForward: alertHistoryTablePageForward,
                                    onBackward: alertHistoryTablePageBackward,
                                }}
                            />
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
