import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconNotebook } from '@posthog/icons'
import {
    LemonSegmentedButton,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Link,
    Spinner,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import type { LemonTableColumn } from '@posthog/lemon-ui'

import { AlertHistoryChart } from 'lib/components/Alerts/views/AlertHistoryChart'
import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { formatDate } from 'lib/utils'

import { alertLogic, CHART_CHECKS_LIMIT, TABLE_CHECKS_PAGE_SIZE } from '../alertLogic'
import type { AlertCheck, AlertType, InvestigationVerdict } from '../types'

const VERDICT_CONFIG: Record<InvestigationVerdict, { label: string; className: string; tooltip: string }> = {
    true_positive: {
        label: 'True positive',
        className: 'text-danger',
        tooltip: 'Agent thinks this is a real anomaly worth looking at.',
    },
    false_positive: {
        label: 'False positive',
        className: 'text-muted',
        tooltip: 'Agent thinks this was a data/release artifact, not a real anomaly.',
    },
    inconclusive: {
        label: 'Inconclusive',
        className: 'text-warning',
        tooltip: 'Agent could not reach a confident conclusion from the available data.',
    },
}

function InvestigationCell({ check }: { check: AlertCheck }): JSX.Element {
    const status = check.investigation_status
    const shortId = check.investigation_notebook_short_id
    const summary = check.investigation_summary?.trim() || null
    const verdict = check.investigation_verdict ?? null
    const suppressed = !!check.notification_suppressed_by_agent

    if (status === 'done') {
        const verdictCfg = verdict ? VERDICT_CONFIG[verdict] : null
        return (
            <div className="flex flex-col gap-1 items-start max-w-md">
                {suppressed && (
                    <Tooltip title="The investigation agent concluded this fire wasn't worth notifying about, so the notification was suppressed.">
                        <LemonTag type="muted" size="small">
                            Notification suppressed
                        </LemonTag>
                    </Tooltip>
                )}
                <Tooltip title={summary || undefined}>
                    <div className="text-sm leading-normal line-clamp-2 text-muted">
                        {verdictCfg && (
                            <Tooltip title={verdictCfg.tooltip}>
                                <span className={`font-semibold ${verdictCfg.className}`}>{verdictCfg.label}</span>
                            </Tooltip>
                        )}
                        {verdictCfg && summary && <span> — </span>}
                        {summary && <span>{summary}</span>}
                    </div>
                </Tooltip>
                {shortId && (
                    <Link to={`/notebooks/${shortId}`} className="inline-flex items-center gap-1 text-sm">
                        <IconNotebook /> View notebook <IconOpenInNew className="text-xs" />
                    </Link>
                )}
            </div>
        )
    }
    if (status === 'running' || status === 'pending') {
        return (
            <span className="inline-flex items-center gap-1 text-secondary">
                <Spinner textColored /> Running
            </span>
        )
    }
    if (status === 'failed') {
        return (
            <Tooltip title="The investigation agent couldn't complete in time. The alert was still delivered. If this keeps happening, you can turn off the investigation agent in this alert's settings.">
                <span className="text-danger">Failed</span>
            </Tooltip>
        )
    }
    if (status === 'skipped') {
        return (
            <Tooltip title="Skipped because another investigation ran for this alert within the last hour.">
                <span className="text-secondary">Skipped</span>
            </Tooltip>
        )
    }
    return <span className="text-secondary">—</span>
}

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

    const investigationAgentEnabled = alertHistoryIsAnomalyDetection && !!alert?.investigation_agent_enabled

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
        if (investigationAgentEnabled) {
            columns.push({
                title: 'Investigation',
                render: (_value, check) => <InvestigationCell check={check} />,
            })
        }
        columns.push({
            title: 'Targets notified',
            key: 'targets_notified',
            align: 'right',
            render: (_value, check) => (check.targets_notified ? 'Yes' : 'No'),
        })
        return columns
    }, [alertHistoryIsAnomalyDetection, investigationAgentEnabled])

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
