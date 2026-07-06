import { LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { isFinishedRunReport, isLiveRunReport, isQueuedRunReport } from '../../inboxMembership'
import { SignalReport } from '../../types'
import { deriveHeadline, parsePrUrlParts } from '../../utils/reportPresentation'
import { hasKnownSourceProduct, knownSourceProductEntries, SourceProductIconRow } from '../badges/sourceProductIcons'
import { RunStatusOrb, RunVariant, VARIANT_META } from './runStatusVariant'

/** Single source of truth for the four-bucket lifecycle of a run-shaped report. */
export function resolveRunVariant(report: SignalReport): RunVariant {
    if (isQueuedRunReport(report)) {
        return 'queued'
    }
    if (isLiveRunReport(report)) {
        return 'live'
    }
    if (isFinishedRunReport(report)) {
        return report.status === 'failed' ? 'failed' : 'completed'
    }
    return 'live'
}

const RUN_VARIANT_TIMESTAMP_LABEL: Record<RunVariant, string> = {
    queued: 'Queued',
    live: 'Started',
    completed: 'Finished',
    failed: 'Failed',
}

function pickTimestamp(report: SignalReport, variant: RunVariant): string {
    if (variant === 'live') {
        return report.created_at
    }
    return report.updated_at ?? report.created_at
}

/** Source-product icon stack reused inside the run card meta row. */
function RunSourceStack({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
    const [primary, ...overflow] = knownSourceProductEntries(sourceProducts)
    if (!primary) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-2 min-w-0">
            <SourceProductIconRow
                entries={[primary, ...overflow]}
                className="inline-flex items-center gap-1.5 shrink-0"
            />
            <span>
                {primary.meta.label}
                {overflow.length > 0 ? ` + ${overflow.length}` : null}
            </span>
        </span>
    )
}

/** PR number from an implementation PR url, e.g. `#12001`. Null when there's no PR. */
function prRef(prUrl: string | null | undefined): string | null {
    const parts = prUrl ? parsePrUrlParts(prUrl) : null
    return parts ? `#${parts.number}` : null
}

export function AgentRunCard({ report }: { report: SignalReport }): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    const pr = prRef(report.implementation_pr_url)
    const variant = resolveRunVariant(report)
    const meta = VARIANT_META[variant]
    const timestampSource = pickTimestamp(report, variant)
    const headline = deriveHeadline(report.summary)

    return (
        <Link
            to={urls.inboxReport('runs', report.id)}
            className="group flex w-full items-start gap-3 rounded border border-primary bg-surface-primary px-4 py-3.5 text-left text-inherit no-underline transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <RunStatusOrb meta={meta} />

            <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                <span className="break-words min-w-0 font-semibold text-sm leading-snug tracking-tight">
                    {report.title ?? 'Untitled run'}
                </span>
                {headline ? (
                    <p className="break-words line-clamp-2 text-xs text-secondary leading-snug m-0">{headline}</p>
                ) : null}
                <div className="flex items-center gap-2 flex-wrap mt-1.5 text-xs text-tertiary leading-none select-none">
                    {hasSource ? (
                        <>
                            <RunSourceStack sourceProducts={report.source_products} />
                            <span aria-hidden>·</span>
                        </>
                    ) : null}
                    <span className="inline-flex items-center gap-1">
                        {RUN_VARIANT_TIMESTAMP_LABEL[variant]} <TZLabel time={timestampSource} />
                    </span>
                </div>
            </div>

            <div className="flex flex-col items-end justify-center gap-1.5 self-stretch shrink-0 border-l border-primary pl-3">
                <LemonTag size="small" type={meta.badgeType} className="select-none">
                    {meta.label}
                </LemonTag>
                {pr ? <span className="font-mono tabular-nums text-[11px] text-tertiary">{pr}</span> : null}
            </div>
        </Link>
    )
}
