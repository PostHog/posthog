import { useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconChevronDown, IconExternal } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { LinkedSignalReport, SignalScoutEmission, SignalScoutRunSummary } from '../../../types'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
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
 *
 * `isDeepLinked` marks the finding the current `/inbox/scouts/<skill>/<finding>` URL points at — it
 * auto-expands, highlights, and scrolls itself into view so a shared link lands on the right card.
 */
export function ScoutEmissionCard({
    skillName,
    emission,
    run,
    report,
    isDeepLinked = false,
    showScout = false,
}: {
    skillName: string
    emission: SignalScoutEmission
    run: SignalScoutRunSummary
    /** The inbox report this finding grouped into, if resolved — renders the "In report" deep-link chip. */
    report: LinkedSignalReport | null
    /** True when this finding is the one the current URL deep-links to. */
    isDeepLinked?: boolean
    /** Cross-fleet listings set this to surface the scout (name in the header, "View scout" footer link). */
    showScout?: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(isDeepLinked)
    const confidencePercent = Math.round((emission.confidence ?? 0) * 100)
    const cardRef = useRef<HTMLDivElement>(null)

    // A deep-linked finding may mount after the URL is already settled (emissions load async), so
    // bring it into view and open it once it appears. Keyed on the finding id so re-selecting a
    // different finding in the same list re-triggers, not on every render.
    useEffect(() => {
        if (isDeepLinked) {
            setExpanded(true)
            cardRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isDeepLinked, emission.finding_id])

    const copyFindingLink = (): void => {
        void copyToClipboard(
            `${window.location.origin}${addProjectIdIfMissing(urls.inboxScout(skillName, emission.finding_id))}`,
            'finding link'
        )
    }

    return (
        <div
            ref={cardRef}
            className={`flex flex-col rounded border bg-bg-light ${
                isDeepLinked ? 'border-accent bg-accent-highlight-secondary' : 'border-primary'
            }`}
        >
            <div className="flex items-center">
                <button
                    type="button"
                    onClick={() => setExpanded((value) => !value)}
                    className="flex flex-1 items-center gap-2 px-3 py-2 text-left"
                    aria-expanded={expanded}
                >
                    <IconChevronDown
                        className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
                    />
                    <SignalReportPriorityBadge priority={emission.severity} />
                    {showScout && (
                        <span className="truncate text-xs font-medium text-default">
                            {prettifyScoutSkillName(skillName)}
                        </span>
                    )}
                    <span className="whitespace-nowrap text-[11px] text-muted tabular-nums">
                        {confidencePercent}% confidence
                    </span>
                    <span className="flex-1" />
                    <span className="whitespace-nowrap text-[11px] text-muted">
                        {humanFriendlyDetailedTime(emission.emitted_at)}
                    </span>
                </button>
                <LemonButton
                    size="xsmall"
                    icon={<IconLink />}
                    tooltip="Copy a link to this finding"
                    className="mr-2 shrink-0"
                    onClick={copyFindingLink}
                />
            </div>

            <div className="px-3 pb-2 pl-9">
                <LemonMarkdown
                    disableImages
                    className={expanded ? 'text-sm text-primary' : 'text-sm text-primary line-clamp-2'}
                >
                    {emission.description || '_No description._'}
                </LemonMarkdown>

                {report && (
                    <Link
                        to={urls.inboxReport('reports', report.id)}
                        className="mt-2 inline-flex max-w-full items-center gap-1 rounded bg-primary-highlight px-2 py-0.5 text-xs font-medium text-primary"
                    >
                        <span className="shrink-0 text-muted">In report:</span>
                        <span className="truncate">{report.title || 'Untitled report'}</span>
                        <IconArrowRight className="size-3 shrink-0" />
                    </Link>
                )}

                {expanded && (
                    <div className="flex items-center flex-wrap gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                        <MonoId label="Finding" value={emission.finding_id} />
                        {showScout && (
                            <Link
                                to={urls.inboxScout(skillName)}
                                className="flex items-center gap-1 font-medium shrink-0"
                            >
                                View {prettifyScoutSkillName(skillName)} <IconArrowRight className="size-3" />
                            </Link>
                        )}
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
