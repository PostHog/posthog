import { useValues } from 'kea'
import { memo, useMemo, useState } from 'react'

import { IconArrowRight, IconChevronDown, IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutRunSummary } from '../../../types'
import {
    deriveRunFailureKind,
    formatRunDuration,
    normalizeRunStatus,
    runDurationSeconds,
    runMatchesFilter,
    runProducedOutput,
    runReportActivity,
    ScoutRunFilter,
    scoutReportActivityLabel,
    SCOUT_RUNS_WINDOW_SPAN,
} from '../../../utils/scoutRunsWindow'

const FILTERS: { value: ScoutRunFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'emitted', label: 'Emitted' },
    { value: 'quiet', label: 'Quiet' },
    { value: 'failed', label: 'Failed' },
]

/** Truncated mono id (run ids are long ULIDs; only the leading chunk earns a row footer). */
function truncateId(value: string): string {
    return value.length > 12 ? `${value.slice(0, 12)}…` : value
}

/** A compact status glyph: ✗ failed · pulsing dot running/queued · ◆ produced output (finding or
 * report) · · quiet. */
function RunGlyph({ run }: { run: SignalScoutRunSummary }): JSX.Element {
    const status = normalizeRunStatus(run.status)
    if (status === 'failed') {
        return <span className="text-danger text-sm font-medium leading-none">✗</span>
    }
    if (status === 'running' || status === 'queued') {
        return <span className="inline-block size-2 shrink-0 rounded-full bg-primary animate-pulse" />
    }
    if (runProducedOutput(run)) {
        return <span className="text-primary-3000 text-sm font-medium leading-none">◆</span>
    }
    return <span className="text-muted text-sm leading-none">·</span>
}

/**
 * One run in the history list. Shares the collapse/expand grammar of `ScoutEmissionCard`: a header
 * (chevron · glyph · timestamp · duration · failure · emitted count) that stays visible, the run
 * summary markdown (2-line preview collapsed, full expanded), and an id/task-run footer when open.
 *
 * Memoized because the 60s runs-window poll re-renders the whole history list; `loadRunsWindow`
 * reconciles run identity (see `reconcileById`) so unchanged runs keep their reference and skip here.
 */
const ScoutRunRow = memo(function ScoutRunRow({ run }: { run: SignalScoutRunSummary }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const now = new Date()
    const status = normalizeRunStatus(run.status)
    const failureKind = deriveRunFailureKind(run, now)
    const duration = formatRunDuration(runDurationSeconds(run, now))
    const emitted = run.emitted_count ?? 0
    const reportActivityLabel = scoutReportActivityLabel(run)
    const { authored: authoredReportIds, edited: editedReportIds } = runReportActivity(run)
    const hasBody = Boolean(run.summary) || status === 'failed' || expanded

    return (
        <div className="flex flex-col rounded border border-primary bg-bg-light">
            <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="flex items-center gap-2 px-3 py-2 text-left"
                aria-expanded={expanded}
            >
                <IconChevronDown
                    className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
                />
                <RunGlyph run={run} />
                <TZLabel
                    time={run.started_at}
                    showPopover={false}
                    className="whitespace-nowrap text-[11px] text-muted"
                />
                {duration && <span className="whitespace-nowrap text-[11px] text-muted">· {duration}</span>}
                {failureKind && (
                    <span className="whitespace-nowrap text-[11px] text-warning">
                        · {failureKind === 'timed_out' ? 'timed out' : 'failed'}
                    </span>
                )}
                <span className="flex-1" />
                {emitted > 0 ? (
                    <span className="whitespace-nowrap rounded bg-primary-highlight px-1.5 py-0.5 text-[11px] font-medium text-primary-3000">
                        {pluralize(emitted, 'signal')} emitted
                    </span>
                ) : reportActivityLabel ? (
                    <span className="whitespace-nowrap rounded bg-primary-highlight px-1.5 py-0.5 text-[11px] font-medium text-primary-3000">
                        {reportActivityLabel}
                    </span>
                ) : status === 'completed' ? (
                    <span className="whitespace-nowrap text-[11px] text-muted">0 signals emitted</span>
                ) : null}
            </button>

            {hasBody && (
                <div className="px-3 pb-2 pl-9">
                    {run.summary ? (
                        <LemonMarkdown
                            disableImages
                            className={expanded ? 'text-sm text-primary' : 'text-sm text-primary line-clamp-2'}
                        >
                            {run.summary}
                        </LemonMarkdown>
                    ) : status === 'failed' ? (
                        <span className="text-sm italic text-muted">
                            No summary — the run ended before writing its close-out. The task run in PostHog is the only
                            diagnostic.
                        </span>
                    ) : null}

                    {expanded && (
                        <div className="flex items-center flex-wrap gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                            <span className="font-mono">{truncateId(run.run_id)}</span>
                            {authoredReportIds.map((reportId) => (
                                <Link
                                    key={reportId}
                                    to={urls.inboxReport('reports', reportId)}
                                    className="flex items-center gap-1 font-medium shrink-0"
                                >
                                    Authored report <IconArrowRight className="size-3" />
                                </Link>
                            ))}
                            {editedReportIds.map((reportId) => (
                                <Link
                                    key={reportId}
                                    to={urls.inboxReport('reports', reportId)}
                                    className="flex items-center gap-1 font-medium shrink-0"
                                >
                                    Edited report <IconArrowRight className="size-3" />
                                </Link>
                            ))}
                            {run.task_url && (
                                <>
                                    <span className="flex-1" />
                                    <Link to={run.task_url} className="flex items-center gap-1 font-medium shrink-0">
                                        Open task run <IconExternal className="size-3" />
                                    </Link>
                                </>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
})

/**
 * The Runs section on the scout detail surface: this scout's runs in the recent window, newest
 * first, with All/Emitted/Quiet/Failed filter chips (each showing its match count). Runs come
 * from `scoutFleetLogic`'s already-polled window rollup (oldest-first timeline order, reversed
 * here) — there's no per-scout runs endpoint yet (api gap 1), so the window is filtered client-side.
 */
export function ScoutRunHistorySection({ skillName }: { skillName: string }): JSX.Element {
    const { rollups, runsWindowLoadedOnce, runsWindowComplete } = useValues(scoutFleetLogic)
    const [filter, setFilter] = useState<ScoutRunFilter>('all')

    // Newest first for a history list; the rollup keeps runs oldest-first for the header timeline.
    const runs = useMemo(() => {
        const windowRuns = rollups.get(skillName)?.runs ?? []
        return [...windowRuns].reverse()
    }, [rollups, skillName])

    const filterCounts = useMemo(() => {
        const counts = new Map<ScoutRunFilter, number>()
        for (const entry of FILTERS) {
            counts.set(entry.value, runs.filter((run) => runMatchesFilter(run, entry.value)).length)
        }
        return counts
    }, [runs])

    const filteredRuns = useMemo(() => runs.filter((run) => runMatchesFilter(run, filter)), [runs, filter])

    // Hold the skeleton until the fleet's runs window has settled once — otherwise a fresh deep-link
    // flashes the empty state before we know this scout's runs.
    const loading = !runsWindowLoadedOnce

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-medium text-default uppercase tracking-wide">Runs</span>
                <span className="flex-1" />
                {FILTERS.map((entry) => (
                    <LemonButton
                        key={entry.value}
                        size="xsmall"
                        type="tertiary"
                        active={filter === entry.value}
                        onClick={() => setFilter(entry.value)}
                    >
                        {entry.label} {filterCounts.get(entry.value) ?? 0}
                    </LemonButton>
                ))}
            </div>

            {loading ? (
                <LemonSkeleton className="h-12 w-full rounded" />
            ) : filteredRuns.length === 0 ? (
                <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                    {runs.length > 0
                        ? `No runs match this filter in the last ${SCOUT_RUNS_WINDOW_SPAN}.`
                        : runsWindowComplete
                          ? `No runs in the last ${SCOUT_RUNS_WINDOW_SPAN}.`
                          : `No runs in the recent window we could load (the last ${SCOUT_RUNS_WINDOW_SPAN} is truncated).`}
                </div>
            ) : (
                <>
                    {filteredRuns.map((run) => (
                        <ScoutRunRow key={run.run_id} run={run} />
                    ))}
                    {!runsWindowComplete && (
                        <span className="text-xs text-muted">
                            Older runs beyond the loaded {SCOUT_RUNS_WINDOW_SPAN} window aren’t shown.
                        </span>
                    )}
                </>
            )}
        </div>
    )
}
