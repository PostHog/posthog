import { useMemo } from 'react'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { SignalScoutRunSummary } from '../../../types'
import {
    deriveRunOutcome,
    formatRunDuration,
    runDurationSeconds,
    ScoutRunOutcome,
    scoutRunOutcomeLabel,
} from '../../../utils/scoutRunsWindow'

// Quiet is the common, healthy baseline so it recedes to muted; saturated color
// only means something happened – blue emission payoff, red/amber trouble. Blue
// (not the orange brand primary) keeps this in step with the desktop Code app.
const OUTCOME_BOX_CLASS: Record<ScoutRunOutcome, string> = {
    emitted: 'bg-brand-blue',
    // A report-channel run produced output too — same payoff blue as an emitting run.
    reported: 'bg-brand-blue',
    quiet: 'bg-border-bold',
    error: 'bg-danger',
    timed_out: 'bg-warning',
    running: 'bg-brand-blue animate-pulse',
    stuck: 'bg-danger animate-pulse',
    queued: 'border border-border-bold bg-transparent',
    unknown: 'bg-border',
}

const MAX_BOXES = 24
const BOX_CLASS = 'block h-3 w-2 shrink-0 rounded-[2px] transition-transform duration-100 hover:scale-y-125'

function runTooltip(run: SignalScoutRunSummary, now: Date): string {
    const parts = [scoutRunOutcomeLabel(run, now)]
    const duration = formatRunDuration(runDurationSeconds(run, now))
    if (duration) {
        parts.push(duration)
    }
    if (run.started_at) {
        parts.push(humanFriendlyDetailedTime(run.started_at))
    }
    return parts.join(' · ')
}

/**
 * One small box per run in the visible window, oldest on the left. Each box
 * links out to cloud's Tasks UI via the run's relative `task_url`; runs without
 * a task link are tooltip-only.
 *
 * Laid out with `flex-row-reverse` (newest first in the DOM) so that when the
 * row is too narrow for every box the container clips the oldest runs off the
 * left edge, keeping the most recent activity — and the controls column to the
 * right — always visible.
 */
export function ScoutRunBoxes({ runs }: { runs: SignalScoutRunSummary[] }): JSX.Element | null {
    const visible = useMemo(() => {
        const now = new Date()
        return runs.slice(-MAX_BOXES).map((run) => ({
            run,
            outcome: deriveRunOutcome(run, now),
            tooltip: runTooltip(run, now),
        }))
    }, [runs])

    if (runs.length === 0) {
        return null
    }
    const hidden = runs.length - visible.length

    // Newest first so flex-row-reverse renders them right-to-left; the oldest
    // runs (and the +N marker) sit at the left edge and clip away first.
    const newestFirst = visible.slice().reverse()

    return (
        <div className="flex flex-row-reverse items-center gap-1 min-w-0 overflow-hidden">
            {newestFirst.map(({ run, outcome, tooltip }) => {
                const boxClass = `${BOX_CLASS} ${OUTCOME_BOX_CLASS[outcome]}`
                if (run.task_url) {
                    const linkTooltip = `${tooltip} · open task run`
                    return (
                        <Tooltip key={run.run_id} title={linkTooltip}>
                            <Link to={run.task_url} className={boxClass}>
                                <span className="sr-only">Run {linkTooltip}</span>
                            </Link>
                        </Tooltip>
                    )
                }
                return (
                    <Tooltip key={run.run_id} title={tooltip}>
                        <span className={boxClass}>
                            <span className="sr-only">Run {tooltip}</span>
                        </span>
                    </Tooltip>
                )
            })}
            {hidden > 0 ? <span className="shrink-0 text-[10px] text-muted">+{hidden}</span> : null}
        </div>
    )
}
