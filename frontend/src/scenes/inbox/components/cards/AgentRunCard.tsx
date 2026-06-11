import clsx from 'clsx'

import { LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { isFinishedRunReport, isLiveRunReport, isQueuedRunReport } from '../../inboxMembership'
import { SignalReport } from '../../types'
import { getSourceProductMeta, hasKnownSourceProduct } from '../badges/sourceProductIcons'

type RunVariant = 'queued' | 'live' | 'completed' | 'failed'

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

interface VariantMeta {
    label: string
    badgeType: LemonTagType
    orbClass: string
    dotClass: string
    ariaLabel: string
}

const VARIANT_META: Record<RunVariant, VariantMeta> = {
    queued: {
        label: 'Queued',
        badgeType: 'default',
        orbClass: 'bg-fill-primary ring-primary',
        dotClass: 'bg-muted',
        ariaLabel: 'Queued',
    },
    live: {
        label: 'Running',
        badgeType: 'highlight',
        orbClass: 'bg-primary-highlight ring-primary',
        dotClass: 'bg-accent animate-pulse',
        ariaLabel: 'In progress',
    },
    completed: {
        label: 'Completed',
        badgeType: 'success',
        orbClass: 'bg-success-highlight ring-success',
        dotClass: 'bg-success',
        ariaLabel: 'Completed',
    },
    failed: {
        label: 'Failed',
        badgeType: 'danger',
        orbClass: 'bg-danger-highlight ring-danger',
        dotClass: 'bg-danger',
        ariaLabel: 'Failed',
    },
}

function pickTimestamp(report: SignalReport, variant: RunVariant): string {
    if (variant === 'live') {
        return report.created_at
    }
    return report.updated_at ?? report.created_at
}

function RunStatusOrb({ meta }: { meta: VariantMeta }): JSX.Element {
    return (
        <div
            className={clsx(
                'flex items-center justify-center h-7 w-7 shrink-0 rounded-full ring-1 ring-inset',
                meta.orbClass
            )}
        >
            <span
                className={clsx('block h-1.5 w-1.5 rounded-full', meta.dotClass)}
                role="img"
                aria-label={meta.ariaLabel}
            />
        </div>
    )
}

/** Source-product icon stack reused inside the run card meta row. */
function RunSourceStack({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
    const items = (sourceProducts ?? [])
        .map((key) => ({ key, meta: getSourceProductMeta(key) }))
        .filter(
            (entry): entry is { key: string; meta: NonNullable<ReturnType<typeof getSourceProductMeta>> } =>
                entry.meta !== null
        )
    if (items.length === 0) {
        return null
    }
    const primary = items[0]
    const overflow = items.slice(1)
    return (
        <span className="inline-flex items-center gap-2 min-w-0">
            <span className="inline-flex items-center gap-1.5 shrink-0">
                {items.map((entry) => {
                    const Icon = entry.meta.Icon
                    return (
                        <span
                            key={entry.key}
                            className="inline-flex shrink-0 items-center"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: entry.meta.color }}
                            aria-hidden
                        >
                            <Icon className="text-xs" />
                        </span>
                    )
                })}
            </span>
            <span>
                {primary.meta.label}
                {overflow.length > 0 ? ` + ${overflow.length}` : null}
            </span>
        </span>
    )
}

export function AgentRunCard({ report }: { report: SignalReport }): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    const runId = `…-${report.id.split('-').pop() ?? report.id}`
    const variant = resolveRunVariant(report)
    const meta = VARIANT_META[variant]
    const timestampSource = pickTimestamp(report, variant)

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
                <span className="font-mono tabular-nums text-[11px] text-tertiary">{runId}</span>
            </div>
        </Link>
    )
}
