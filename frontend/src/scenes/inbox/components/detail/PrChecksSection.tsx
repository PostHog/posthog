import { useValues } from 'kea'

import { IconCheckCircle, IconClock, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { PullRequestCheck, SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

type CheckVariant = 'failure' | 'cancelled' | 'pending' | 'success' | 'neutral'

/** Collapse a GitHub check's (status, conclusion) pair into one of the buckets we render. */
function resolveCheckVariant(check: PullRequestCheck): CheckVariant {
    if (check.status !== 'completed') {
        return 'pending'
    }
    switch (check.conclusion) {
        case 'success':
            return 'success'
        case 'failure':
        case 'timed_out':
        case 'action_required':
        case 'startup_failure':
            return 'failure'
        case 'cancelled':
            return 'cancelled'
        default:
            // neutral / skipped / stale / null-on-completed
            return 'neutral'
    }
}

const VARIANT_META: Record<CheckVariant, { icon: JSX.Element; label: string; className: string }> = {
    failure: { icon: <IconWarning />, label: 'Failed', className: 'text-danger' },
    cancelled: { icon: <IconX />, label: 'Cancelled', className: 'text-muted' },
    pending: { icon: <IconClock />, label: 'Running', className: 'text-warning' },
    success: { icon: <IconCheckCircle />, label: 'Passed', className: 'text-success' },
    neutral: { icon: <IconMinus />, label: 'Skipped', className: 'text-muted' },
}

// Failed first, then in-flight, then the rest — the buckets worth a human's attention lead.
const VARIANT_ORDER: CheckVariant[] = ['failure', 'cancelled', 'pending', 'success', 'neutral']

/**
 * "CI checks" section for a report's implementation PR: the GitHub Actions check runs and legacy
 * commit statuses of the PR's head commit, polled every 15s by `inboxReportDetailLogic` while the
 * detail is open. Read-only — each row links out to the check on GitHub.
 */
export function PrChecksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { prChecks, prChecksLoading, prChecksError } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )

    // Never loaded yet: show a skeleton. Loaded-but-empty: nothing to show, so drop the section.
    if (prChecks === null) {
        if (!prChecksLoading && !prChecksError) {
            return null
        }
    } else if (prChecks.length === 0 && !prChecksError) {
        return null
    }

    const sorted = [...(prChecks ?? [])].sort(
        (a, b) => VARIANT_ORDER.indexOf(resolveCheckVariant(a)) - VARIANT_ORDER.indexOf(resolveCheckVariant(b))
    )
    const failing = sorted.filter((c) => resolveCheckVariant(c) === 'failure').length
    const pending = sorted.filter((c) => resolveCheckVariant(c) === 'pending').length

    return (
        <DetailSection
            icon={<IconCheckCircle />}
            title="CI checks"
            collapsible
            defaultCollapsed={sorted.length > 0 && failing === 0 && pending === 0}
            rightSlot={
                sorted.length > 0 ? (
                    <span className="text-[0.6875rem] text-tertiary tabular-nums">
                        {failing > 0 ? `${failing} failing · ` : ''}
                        {pending > 0 ? `${pending} running · ` : ''}
                        {sorted.length} total
                    </span>
                ) : undefined
            }
        >
            {prChecksError ? (
                <p className="m-0 py-2 text-sm text-danger">{prChecksError}</p>
            ) : prChecks === null ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-6 w-full" />
                    <LemonSkeleton className="h-6 w-4/5" />
                </div>
            ) : (
                <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                    {sorted.map((check, i) => {
                        const variant = resolveCheckVariant(check)
                        const meta = VARIANT_META[variant]
                        const row = (
                            <span className="flex items-center gap-2 min-w-0">
                                <Tooltip title={meta.label}>
                                    <span className={`flex shrink-0 items-center [&_svg]:size-4 ${meta.className}`}>
                                        {meta.icon}
                                    </span>
                                </Tooltip>
                                <span className="truncate text-sm">{check.name}</span>
                            </span>
                        )
                        return (
                            <li
                                key={`${check.name}-${i}`}
                                className="flex items-center gap-2 rounded px-2 py-1 hover:bg-fill-highlight-50"
                            >
                                {check.url ? (
                                    <Link to={check.url} target="_blank" className="min-w-0 text-primary">
                                        {row}
                                    </Link>
                                ) : (
                                    row
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}
        </DetailSection>
    )
}
