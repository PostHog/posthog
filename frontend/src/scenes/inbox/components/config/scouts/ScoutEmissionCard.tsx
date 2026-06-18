import { useState } from 'react'

import { IconChevronDown, IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { SignalScoutEmission, SignalScoutRunSummary } from '../../../types'
import { SignalReportPriorityBadge } from '../../badges/SignalReportPriorityBadge'

/** Truncated mono identifier rendering for the footer finding id. */
function MonoId({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1">
            <span>{label}</span>
            <span className="font-mono">{value.length > 12 ? `${value.slice(0, 12)}…` : value}</span>
        </span>
    )
}

/**
 * One emitted finding in the scout detail Signals section. Shares the collapse/expand grammar of
 * the run rows: a header (chevron · severity · confidence · timestamp) that stays visible, a 2-line
 * markdown preview when collapsed, and the full markdown plus an id/task-run footer when expanded.
 */
export function ScoutEmissionCard({
    emission,
    run,
}: {
    emission: SignalScoutEmission
    run: SignalScoutRunSummary
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const confidencePercent = Math.round((emission.confidence ?? 0) * 100)

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
                <SignalReportPriorityBadge priority={emission.severity} />
                <span className="whitespace-nowrap text-[11px] text-muted tabular-nums">
                    {confidencePercent}% confidence
                </span>
                <span className="flex-1" />
                <span className="whitespace-nowrap text-[11px] text-muted">
                    {humanFriendlyDetailedTime(emission.emitted_at)}
                </span>
            </button>

            <div className="px-3 pb-2 pl-9">
                <LemonMarkdown className={expanded ? 'text-sm text-primary' : 'text-sm text-primary line-clamp-2'}>
                    {emission.description || '_No description._'}
                </LemonMarkdown>

                {expanded && (
                    <div className="flex items-center flex-wrap gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                        <MonoId label="Finding" value={emission.finding_id} />
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
        </div>
    )
}
