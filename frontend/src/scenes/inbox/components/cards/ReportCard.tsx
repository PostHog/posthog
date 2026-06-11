import clsx from 'clsx'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconBolt, IconThumbsDown } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { SignalReport } from '../../types'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
    parseConventionalCommitTitle,
} from '../../utils/reportPresentation'
import { ForYouBadge } from '../badges/ForYouBadge'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { getSourceProductMeta, hasKnownSourceProduct } from '../badges/sourceProductIcons'
import { openDismissReportDialog } from '../shell/DismissReportDialog'

// ── Shared card sub-components ────────────────────────────────────────────────

const PRIORITY_CLASSES: Record<string, string> = {
    P0: 'bg-danger-highlight text-danger',
    P1: 'bg-warning-highlight text-warning',
    P2: 'bg-warning-highlight text-warning',
    P3: 'bg-fill-primary text-secondary',
    P4: 'bg-fill-primary text-tertiary',
}

export function PriorityMonogram({ priority }: { priority: SignalReport['priority'] }): JSX.Element {
    const label = priority ?? '–'
    const toneClass = priority
        ? (PRIORITY_CLASSES[priority] ?? 'bg-fill-primary text-tertiary')
        : 'bg-fill-primary text-tertiary'
    return (
        <div
            className={clsx(
                'flex h-6 w-6 shrink-0 items-center justify-center rounded font-bold text-[9px] tracking-tight',
                toneClass
            )}
            aria-label={priority ? `Priority ${priority}` : 'Priority unknown'}
            role="img"
        >
            {label}
        </div>
    )
}

export function ConventionalCommitScopeTag({ type, scope }: { type: string; scope: string | null }): JSX.Element {
    const label = scope ? `${type}(${scope})` : type
    return (
        <LemonTag size="small" className="shrink-0 font-mono select-none" title={label}>
            {label}
        </LemonTag>
    )
}

/** Icon stack + primary source-product label, with a `+ n` tail when more sources contributed. */
export function InboxCardSourceMeta({ sourceProducts }: { sourceProducts?: string[] | null }): JSX.Element | null {
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
        <div className="flex items-center gap-2 min-w-0 text-xs text-tertiary leading-none select-none">
            <div className="flex items-center gap-1.5 shrink-0">
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
            </div>
            <span>
                {primary.meta.label}
                {overflow.length > 0 ? ` + ${overflow.length}` : null}
            </span>
        </div>
    )
}

// ── ReportCard ────────────────────────────────────────────────────────────────

export function ReportCard({ report }: { report: SignalReport }): JSX.Element {
    const hasSource = hasKnownSourceProduct(report.source_products)
    const updatedAtRaw = report.updated_at ?? report.created_at
    const updatedAtDate = updatedAtRaw ? new Date(updatedAtRaw) : null
    const updatedAtLabel =
        updatedAtDate && !Number.isNaN(updatedAtDate.getTime())
            ? updatedAtDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
            : null
    const isReady = report.status === 'ready'
    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const cardTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const headline = deriveHeadline(report.summary)
    const detailUrl = urls.inboxReport('reports', report.id)

    const [isDismissing, setIsDismissing] = useState(false)

    const hasMetadata = hasSource || !isReady || report.actionability != null || report.is_suggested_reviewer === true

    const onDismiss = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        openDismissReportDialog({
            reportTitle: cardTitle,
            onConfirm: async ({ reason, note }) => {
                setIsDismissing(true)
                try {
                    await api.signalReports.setState(report.id, {
                        state: 'suppressed',
                        dismissal_reason: reason,
                        ...(note ? { dismissal_note: note } : {}),
                    })
                } finally {
                    setIsDismissing(false)
                }
            },
        })
    }

    return (
        <div className="group flex w-full items-stretch gap-3 rounded border border-dashed border-primary bg-surface-primary px-4 py-3.5 transition-all duration-150 hover:border-secondary hover:bg-surface-secondary hover:shadow-sm">
            <Link to={detailUrl} className="flex min-w-0 flex-1 items-start gap-3 text-left text-inherit no-underline">
                <PriorityMonogram priority={report.priority} />

                <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                    <div className="flex items-center gap-1 flex-wrap min-w-0">
                        {conventionalTitle && (
                            <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                        )}
                        <span className="min-w-0 flex-1 break-words font-semibold text-sm leading-snug">
                            {cardTitle}
                        </span>
                    </div>

                    <div className={clsx('mt-0.5 min-w-0', !isReady && 'opacity-80')}>
                        {headline ? (
                            <p className="break-words line-clamp-2 text-xs text-secondary leading-snug m-0">
                                {headline}
                            </p>
                        ) : (
                            <p className="break-words line-clamp-2 text-xs text-tertiary italic leading-snug m-0">
                                No summary yet – still collecting context.
                            </p>
                        )}
                    </div>

                    {hasMetadata ? (
                        <div className="flex items-center flex-wrap mt-1.5 min-w-0 gap-2.5">
                            <InboxCardSourceMeta sourceProducts={report.source_products} />
                            {(!isReady || !report.actionability) && <SignalReportStatusBadge status={report.status} />}
                            {report.actionability && (
                                <SignalReportActionabilityBadge actionability={report.actionability} />
                            )}
                            {report.is_suggested_reviewer && <ForYouBadge />}
                        </div>
                    ) : null}
                </div>
            </Link>

            <div className="flex flex-col items-end justify-between shrink-0 border-l border-primary pl-3 gap-1.5">
                {updatedAtLabel && (
                    <span className="shrink-0 text-xs text-tertiary tabular-nums">{updatedAtLabel}</span>
                )}

                <div className="flex items-center gap-1.5 my-auto">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconThumbsDown />}
                        tooltip="Dismiss this report"
                        aria-label="Dismiss this report"
                        loading={isDismissing}
                        onClick={onDismiss}
                    />
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                            router.actions.push(detailUrl)
                        }}
                    >
                        Review
                    </LemonButton>
                </div>

                <span className="flex items-center gap-1 shrink-0 text-xs text-tertiary">
                    <IconBolt className="text-[11px]" />
                    <span className="tabular-nums">
                        {report.signal_count} finding{report.signal_count !== 1 ? 's' : ''}
                    </span>
                </span>
            </div>
        </div>
    )
}
