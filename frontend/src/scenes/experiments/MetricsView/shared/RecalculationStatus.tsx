import { useActions, useValues } from 'kea'

import { IconBell, IconCheck, IconInfo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useAnimatedNumber } from '@posthog/quill-charts'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { ExperimentLastRefreshText } from 'scenes/experiments/ExperimentView/ExperimentReloadAction'

import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { experimentResultsNotificationLogic } from '~/scenes/experiments/experimentResultsNotificationLogic'
import { Experiment } from '~/types'

import type { ExperimentMetricsRecalculationApi } from 'products/experiments/frontend/generated/api.schemas'

/**
 * Always-on status line for the recalculation flow. Renders exactly one state from
 * `recalculationDisplayState`; the in-flight states read live ClickHouse progress off the poll.
 * Only rendered behind EXPERIMENTS_METRICS_RECALCULATION (see ExperimentView).
 */
export function RecalculationStatus({ experiment }: { experiment: Experiment }): JSX.Element {
    const { recalculationDisplayState, currentRecalculation, totalMetricsCount } = useValues(
        experimentMetricsLogic({ experiment })
    )
    /**
     * Mounted here rather than inside the in-flight branch so the finish-edge subscription that
     * fires the browser notification is still alive when the bar swaps to a terminal state.
     */
    const notificationLogic = experimentResultsNotificationLogic({ experiment })
    const { notifyWhenResultsReady } = useValues(notificationLogic)
    const { subscribeToResultsNotification } = useActions(notificationLogic)

    switch (recalculationDisplayState) {
        case 'initial':
            return (
                <StatusBar>
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                        <Spinner textColored className="text-sm text-accent" />
                        <span className="font-medium">Loading metrics…</span>
                    </span>
                </StatusBar>
            )
        case 'cold':
        case 'refreshing':
            return (
                <InFlightStatus
                    recalculation={currentRecalculation}
                    notifyWhenResultsReady={notifyWhenResultsReady}
                    onSubscribe={subscribeToResultsNotification}
                />
            )
        case 'partial':
        case 'resting':
            return (
                <StatusBar>
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                        <IconCheck className="text-success text-sm" />
                        <span className="font-medium">
                            {totalMetricsCount} {totalMetricsCount === 1 ? 'metric' : 'metrics'}
                        </span>
                        {recalculationDisplayState === 'partial' && (
                            <span className="text-danger font-medium">
                                · {currentRecalculation?.failed_metrics} failed
                            </span>
                        )}
                    </span>
                    {currentRecalculation?.completed_at && (
                        <>
                            <LemonDivider vertical className="h-3.5" />
                            <span className="flex items-center gap-1 whitespace-nowrap text-muted text-xs [&_span]:align-baseline">
                                <span>Results calculated </span>
                                <ExperimentLastRefreshText lastRefresh={currentRecalculation.completed_at} />
                            </span>
                        </>
                    )}
                </StatusBar>
            )
    }
}

function InFlightStatus({
    recalculation,
    notifyWhenResultsReady,
    onSubscribe,
}: {
    recalculation: ExperimentMetricsRecalculationApi | null
    notifyWhenResultsReady: boolean
    onSubscribe: () => void
}): JSX.Element {
    const rowsRead = recalculation?.rows_read ?? undefined
    const succeeded = recalculation?.completed_metrics ?? 0
    const failed = recalculation?.failed_metrics ?? 0
    const total = recalculation?.total_metrics ?? 0
    /**
     * Pending (not yet resolved, not currently sampled as running) keeps the segment truthful in those gaps.
     */
    const pending = Math.max(0, total - succeeded - failed)
    return (
        <StatusBar>
            <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Spinner textColored className="text-sm text-accent" />
                <CountsSegment pending={pending} succeeded={succeeded} failed={failed} />
                <span className="text-muted text-xs">· running in the background</span>
                <Tooltip title="We're computing each metric against the latest data. This runs server-side so you can leave this page; results appear as each metric finishes.">
                    <IconInfo className="text-muted text-xs" />
                </Tooltip>
                {rowsRead !== undefined && (
                    <ClimbingRows
                        rowsRead={rowsRead}
                        estimatedRows={recalculation?.estimated_rows_total ?? undefined}
                    />
                )}
            </span>
            {notifyWhenResultsReady ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconCheck />}
                    disabledReason="Keep this tab open to get notified"
                    className="ml-auto"
                >
                    We'll notify you
                </LemonButton>
            ) : (
                <LemonButton size="xsmall" icon={<IconBell />} onClick={onSubscribe} className="ml-auto">
                    Notify me
                </LemonButton>
            )}
        </StatusBar>
    )
}

function StatusBar({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-8 w-full flex-wrap items-center gap-2.5 rounded border border-primary bg-surface-secondary px-2.5 py-1 text-sm">
            {children}
        </div>
    )
}

function CountsSegment({
    pending,
    succeeded,
    failed,
}: {
    pending: number
    succeeded: number
    failed: number
}): JSX.Element {
    // "running" is only shown when the live sample caught a query mid-flight; pending covers the rest.
    const parts: JSX.Element[] = []

    if (pending > 0) {
        parts.push(<span key="pending">{pending} pending</span>)
    }
    parts.push(
        <span key="succeeded" className="text-success">
            {succeeded} succeeded
        </span>
    )
    if (failed > 0) {
        parts.push(
            <span key="failed" className="text-danger">
                {failed} failed
            </span>
        )
    }
    return (
        <span className="flex items-center gap-1 whitespace-nowrap font-medium">
            {parts.map((part, i) => (
                <span key={part.key} className="flex items-center gap-1">
                    {i > 0 && <span>·</span>}
                    {part}
                </span>
            ))}
        </span>
    )
}

function ClimbingRows({ rowsRead, estimatedRows }: { rowsRead: number; estimatedRows?: number }): JSX.Element {
    const showCeiling = estimatedRows !== undefined && estimatedRows >= rowsRead

    const animatedRowsRead = useAnimatedNumber(rowsRead, 350)
    const animatedEstimatedTotal = useAnimatedNumber(estimatedRows ?? 0, 350)

    return (
        <span className="text-muted text-xs whitespace-nowrap">
            · {humanFriendlyNumber(animatedRowsRead, 0)}
            {showCeiling && ` / ${humanFriendlyNumber(animatedEstimatedTotal, 0)}`} rows read
        </span>
    )
}
