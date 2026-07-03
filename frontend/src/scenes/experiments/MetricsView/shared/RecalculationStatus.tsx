import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { TextMorph } from 'torph/react'

import { IconBell, IconCheck, IconInfo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { experimentResultsNotificationLogic } from '~/scenes/experiments/experimentResultsNotificationLogic'
import { Experiment } from '~/types'

import type { ExperimentMetricsRecalculationApi } from 'products/experiments/frontend/generated/api.schemas'

const RECALCULATION_LOADING_MESSAGES = [
    'Snuffling through spiky piles for metrics…',
    'Counting quills, clicks, and conversions…',
    'Scurrying through the underbrush for results…',
    'Hoarding shiny little significant digits…',
    'Padding softly through fields of variants…',
    'Untangling prickly paths to results…',
    'Balancing nuts, berries, and confidence intervals…',
]

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
                                <span>Refreshed</span>
                                <TZLabel time={currentRecalculation.completed_at} timestampStyle="relative" />
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
    const running = recalculation?.running_metrics ?? 0
    const succeeded = recalculation?.completed_metrics ?? 0
    const failed = recalculation?.failed_metrics ?? 0
    const total = recalculation?.total_metrics ?? 0
    /**
     * `running` is a momentary sample of system.processes, so it reads 0 between per-metric queries.
     * Pending (not yet resolved, not currently sampled as running) keeps the segment truthful in those gaps.
     */
    const pending = Math.max(0, total - succeeded - failed - running)
    return (
        <StatusBar>
            <span className="flex items-center gap-1.5 whitespace-nowrap">
                <Spinner textColored className="text-sm text-accent" />
                <CountsSegment running={running} pending={pending} succeeded={succeeded} failed={failed} />
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
                <RotatingMessage />
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
    running,
    pending,
    succeeded,
    failed,
}: {
    running: number
    pending: number
    succeeded: number
    failed: number
}): JSX.Element {
    // "running" is only shown when the live sample caught a query mid-flight; pending covers the rest.
    const parts: JSX.Element[] = []
    if (running > 0) {
        parts.push(<span key="running">{running} running</span>)
    }
    if (pending > 0 || running === 0) {
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
    return (
        <span className="text-muted text-xs whitespace-nowrap">
            · {humanFriendlyNumber(rowsRead, 0)}
            {showCeiling && ` / ${humanFriendlyNumber(estimatedRows, 0)}`} rows
        </span>
    )
}

function RotatingMessage(): JSX.Element {
    const [index, setIndex] = useState(0)
    const { isVisible } = usePageVisibility()

    useEffect(() => {
        if (!isVisible) {
            return
        }
        const interval = setInterval(
            () => {
                setIndex((current) => {
                    let next = Math.floor(Math.random() * RECALCULATION_LOADING_MESSAGES.length)
                    if (next === current) {
                        next = (next + 1) % RECALCULATION_LOADING_MESSAGES.length
                    }
                    return next
                })
            },
            3000 + Math.random() * 2000
        )
        return () => clearInterval(interval)
    }, [isVisible])

    return (
        <TextMorph as="span" className="text-muted text-xs">
            {`· ${RECALCULATION_LOADING_MESSAGES[index]}`}
        </TextMorph>
    )
}
