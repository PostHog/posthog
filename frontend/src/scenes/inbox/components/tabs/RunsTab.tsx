import { useMemo, useState } from 'react'

import { IconBrain } from '@posthog/icons'

import { isFinishedRunReport, isLiveRunReport, isQueuedRunReport } from '../../inboxMembership'
import { SignalReport } from '../../types'
import { AgentRunCard } from '../cards/AgentRunCard'

const RECENTLY_FINISHED_LIMIT = 10
const QUEUED_LIMIT = 10

function timestampMs(value: string | null | undefined): number {
    if (!value) {
        return 0
    }
    const ms = new Date(value).getTime()
    return Number.isFinite(ms) ? ms : 0
}

export function RunsTab({ reports }: { reports: SignalReport[] }): JSX.Element {
    const [showAllFinished, setShowAllFinished] = useState(false)
    const [showAllQueued, setShowAllQueued] = useState(false)

    const { queuedRuns, liveRuns, finishedRuns } = useMemo(() => {
        const queued: SignalReport[] = []
        const live: SignalReport[] = []
        const finished: SignalReport[] = []
        for (const report of reports) {
            if (isQueuedRunReport(report)) {
                queued.push(report)
            } else if (isLiveRunReport(report)) {
                live.push(report)
            } else if (isFinishedRunReport(report)) {
                finished.push(report)
            }
        }
        const newestFirst = (a: SignalReport, b: SignalReport): number =>
            timestampMs(b.updated_at ?? b.created_at) - timestampMs(a.updated_at ?? a.created_at)
        queued.sort(newestFirst)
        live.sort(newestFirst)
        finished.sort(newestFirst)
        return { queuedRuns: queued, liveRuns: live, finishedRuns: finished }
    }, [reports])

    const visibleFinishedRuns = showAllFinished ? finishedRuns : finishedRuns.slice(0, RECENTLY_FINISHED_LIMIT)
    const hiddenFinishedCount = Math.max(0, finishedRuns.length - visibleFinishedRuns.length)
    const finishedShowAll = resolveShowAllControl(
        finishedRuns.length,
        RECENTLY_FINISHED_LIMIT,
        hiddenFinishedCount,
        showAllFinished,
        () => setShowAllFinished(true),
        () => setShowAllFinished(false)
    )

    const visibleQueuedRuns = showAllQueued ? queuedRuns : queuedRuns.slice(0, QUEUED_LIMIT)
    const hiddenQueuedCount = Math.max(0, queuedRuns.length - visibleQueuedRuns.length)
    const queuedShowAll = resolveShowAllControl(
        queuedRuns.length,
        QUEUED_LIMIT,
        hiddenQueuedCount,
        showAllQueued,
        () => setShowAllQueued(true),
        () => setShowAllQueued(false)
    )

    const hasAnyRuns = queuedRuns.length > 0 || liveRuns.length > 0 || finishedRuns.length > 0

    return (
        <div className="mx-auto max-w-3xl flex flex-col gap-4 px-6 py-4">
            {!hasAnyRuns ? (
                <div className="mx-auto max-w-md flex flex-col items-center text-center py-16 gap-2">
                    <div className="flex items-center justify-center h-12 w-12 rounded-full bg-fill-primary text-secondary mb-1">
                        <IconBrain className="text-2xl" />
                    </div>
                    <h3 className="text-base font-semibold m-0">No agents are working on anything right now</h3>
                    <p className="text-sm text-tertiary m-0">
                        When Self-driving kicks one off, you'll see the live run land here until it finishes as a Pull
                        request or a Report.
                    </p>
                </div>
            ) : (
                <div className="flex flex-col gap-5">
                    {queuedRuns.length > 0 && (
                        <RunsSection
                            title="Queued"
                            count={queuedRuns.length}
                            runs={visibleQueuedRuns}
                            showAll={queuedShowAll}
                        />
                    )}
                    <RunsSection
                        title="Live"
                        count={liveRuns.length}
                        isLive
                        runs={liveRuns}
                        empty={{
                            title: 'Nothing in motion right now',
                            description: 'Self-driving will queue something up here when it kicks off a run.',
                        }}
                    />
                    {finishedRuns.length > 0 && (
                        <RunsSection
                            title="Recently finished"
                            count={finishedRuns.length}
                            runs={visibleFinishedRuns}
                            showAll={finishedShowAll}
                        />
                    )}
                </div>
            )}
        </div>
    )
}

type ShowAllControl =
    | { kind: 'expand'; hiddenCount: number; onClick: () => void }
    | { kind: 'collapse'; onClick: () => void }

function resolveShowAllControl(
    totalCount: number,
    limit: number,
    hiddenCount: number,
    expanded: boolean,
    onExpand: () => void,
    onCollapse: () => void
): ShowAllControl | undefined {
    if (hiddenCount > 0) {
        return { kind: 'expand', hiddenCount, onClick: onExpand }
    }
    if (expanded && totalCount > limit) {
        return { kind: 'collapse', onClick: onCollapse }
    }
    return undefined
}

interface RunsSectionProps {
    title: string
    count: number
    description?: string
    isLive?: boolean
    runs: SignalReport[]
    empty?: { title: string; description: string }
    showAll?: ShowAllControl
}

function RunsSection({ title, count, description, isLive, runs, empty, showAll }: RunsSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-0.5 cursor-default select-none">
                <div className="flex items-center gap-2">
                    <span className="font-semibold text-[13px] text-default">{title}</span>
                    <span className="text-xs text-tertiary tabular-nums">{count}</span>
                    {isLive && count > 0 && (
                        <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
                    )}
                </div>
                {description && <span className="text-xs text-secondary leading-snug">{description}</span>}
            </div>
            {runs.length === 0 && empty ? (
                <div className="flex items-center gap-3 cursor-default select-none rounded border border-dashed border-primary bg-surface-secondary px-4 py-3.5">
                    <div className="flex items-center justify-center h-8 w-8 shrink-0 rounded-full bg-fill-primary ring-1 ring-inset ring-primary">
                        <IconBrain className="text-tertiary" />
                    </div>
                    <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                        <span className="font-medium text-[13px] text-default">{empty.title}</span>
                        <span className="text-xs text-tertiary leading-snug">{empty.description}</span>
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {runs.map((report) => (
                        <AgentRunCard key={report.id} report={report} />
                    ))}
                </div>
            )}
            {showAll && (
                <button
                    type="button"
                    onClick={showAll.onClick}
                    className="self-start rounded px-1.5 py-1 font-medium text-xs text-accent hover:bg-accent-highlight"
                >
                    {showAll.kind === 'collapse' ? 'Show less' : `Show all ${showAll.hiddenCount} more`}
                </button>
            )}
        </div>
    )
}
