import { useValues } from 'kea'

import {
    IconCheckCircle,
    IconClockRewind,
    IconExternal,
    IconMinus,
    IconSpinner,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import type { PullRequestCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'

type CheckVariant = 'failure' | 'cancelled' | 'pending' | 'stale' | 'success' | 'neutral'

/** Collapse a GitHub check's (status, conclusion) pair into one of the buckets we render. */
function resolveCheckVariant(check: PullRequestCheckApi): CheckVariant {
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
        case 'stale':
            return 'stale'
        default:
            // neutral / skipped / null-on-completed
            return 'neutral'
    }
}

const VARIANT_META: Record<
    CheckVariant,
    { icon: JSX.Element; label: string; iconClassName: string; summaryClassName: string }
> = {
    failure: {
        icon: <IconWarning />,
        label: 'Failed',
        iconClassName: 'text-danger',
        summaryClassName: 'text-danger',
    },
    cancelled: {
        icon: <IconX />,
        label: 'Cancelled',
        iconClassName: 'text-muted',
        summaryClassName: 'text-secondary',
    },
    pending: {
        icon: <IconSpinner className="animate-spin motion-reduce:animate-none" />,
        label: 'Running',
        iconClassName: 'text-warning',
        summaryClassName: 'text-warning',
    },
    stale: {
        icon: <IconClockRewind />,
        label: 'Stale',
        iconClassName: 'text-muted',
        summaryClassName: 'text-secondary',
    },
    success: {
        icon: <IconCheckCircle />,
        label: 'Successful',
        iconClassName: 'text-success',
        summaryClassName: 'text-success',
    },
    neutral: {
        icon: <IconMinus />,
        label: 'Skipped',
        iconClassName: 'text-muted',
        summaryClassName: 'text-tertiary',
    },
}

// Failed first, then in-flight, then the rest — the buckets worth a human's attention lead.
const VARIANT_ORDER: CheckVariant[] = ['failure', 'pending', 'cancelled', 'stale', 'success', 'neutral']

function CheckSummary({ variant, count }: { variant: CheckVariant; count: number }): JSX.Element | null {
    if (count === 0) {
        return null
    }

    const meta = VARIANT_META[variant]
    return (
        <span className={`inline-flex items-center gap-1 whitespace-nowrap ${meta.summaryClassName}`}>
            <span className={`flex items-center [&_svg]:size-3 ${meta.iconClassName}`}>{meta.icon}</span>
            <span className="font-medium tabular-nums">{count}</span>
            <span>{meta.label.toLowerCase()}</span>
        </span>
    )
}

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

    // Resolve each check's variant once, then sort/count off it — failed first, then in-flight, then
    // the rest, so the buckets worth a human's attention lead.
    const sorted = (prChecks ?? [])
        .map((check) => ({ check, variant: resolveCheckVariant(check) }))
        .sort((a, b) => VARIANT_ORDER.indexOf(a.variant) - VARIANT_ORDER.indexOf(b.variant))
    const counts = sorted.reduce<Record<CheckVariant, number>>(
        (result, { variant }) => {
            result[variant] += 1
            return result
        },
        { failure: 0, cancelled: 0, pending: 0, stale: 0, success: 0, neutral: 0 }
    )
    const hasChecksNeedingAttention =
        counts.failure > 0 || counts.cancelled > 0 || counts.pending > 0 || counts.stale > 0

    return (
        <DetailSection
            // `DetailSection` reads `defaultCollapsed` only on mount. This section mounts while
            // `prChecks` is still null (skeleton), when the "all green → collapse" default computes to
            // false, so remount once the checks resolve to let the settled default take effect.
            key={prChecks === null ? 'checks-loading' : 'checks-loaded'}
            icon={<IconCheckCircle />}
            title="CI checks"
            collapsible
            defaultCollapsed={sorted.length > 0 && !hasChecksNeedingAttention}
            rightSlot={
                sorted.length > 0 ? (
                    <span className="flex items-center justify-end gap-x-2.5 gap-y-1 flex-wrap text-[0.6875rem]">
                        {VARIANT_ORDER.map((variant) => (
                            <CheckSummary key={variant} variant={variant} count={counts[variant]} />
                        ))}
                    </span>
                ) : undefined
            }
        >
            {prChecksError ? (
                <div className="rounded border border-danger bg-danger-highlight px-3 py-2.5 text-sm text-danger">
                    {prChecksError}
                </div>
            ) : prChecks === null ? (
                <div className="overflow-hidden rounded border border-primary bg-surface-primary">
                    <LemonSkeleton className="h-10 w-full rounded-none" />
                    <LemonSkeleton className="h-10 w-full rounded-none border-t border-primary" />
                    <LemonSkeleton className="h-10 w-full rounded-none border-t border-primary" />
                </div>
            ) : (
                <ul className="m-0 max-h-96 overflow-y-auto rounded border border-primary bg-surface-primary p-0 list-none divide-y divide-border">
                    {sorted.map(({ check, variant }, i) => {
                        const meta = VARIANT_META[variant]
                        const row = (
                            <>
                                <span
                                    className={`flex shrink-0 items-center [&_svg]:size-[1.125rem] ${meta.iconClassName}`}
                                    aria-hidden
                                >
                                    {meta.icon}
                                </span>
                                <span
                                    className="min-w-0 flex-1 truncate text-sm font-medium text-primary"
                                    title={check.name}
                                >
                                    {check.name}
                                </span>
                                <span className="shrink-0 text-xs text-tertiary transition-colors group-hover:text-secondary">
                                    {meta.label}
                                </span>
                                {check.url && (
                                    <IconExternal className="size-3.5 shrink-0 text-tertiary opacity-60 transition-opacity group-hover:opacity-100" />
                                )}
                            </>
                        )
                        return (
                            <li key={`${check.name}-${i}`}>
                                {check.url ? (
                                    <Link
                                        to={check.url}
                                        target="_blank"
                                        className="group flex min-w-0 items-center gap-2.5 px-3 py-2.5 text-primary no-underline transition-colors hover:bg-fill-highlight-50 hover:text-primary focus-visible:bg-fill-highlight-50"
                                    >
                                        {row}
                                    </Link>
                                ) : (
                                    <span className="group flex min-w-0 items-center gap-2.5 px-3 py-2.5">{row}</span>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}
        </DetailSection>
    )
}
