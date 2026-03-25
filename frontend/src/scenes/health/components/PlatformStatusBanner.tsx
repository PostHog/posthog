import { useValues } from 'kea'

import { IconCloud } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { healthMenuLogic } from 'lib/components/HealthMenu/healthMenuLogic'
import type { PostHogStatusBadgeStatus, PostHogStatusType } from 'lib/components/HealthMenu/healthMenuLogic'
import { cn } from 'lib/utils/css-classes'

import { INCIDENT_IO_STATUS_PAGE_BASE } from '~/layout/navigation-3000/incident/incidentStatus'

const STATUS_LABELS: Record<PostHogStatusType, string> = {
    operational: 'Operational',
    degraded_performance: 'Degraded performance',
    partial_outage: 'Partial outage',
    major_outage: 'Major outage',
}

const STATUS_STYLES: Record<
    PostHogStatusBadgeStatus,
    {
        accentLine: string
        iconContainer: string
        icon: string
        badge: string
    }
> = {
    success: {
        accentLine: 'bg-success',
        iconContainer: 'border-success/40 bg-success-highlight',
        icon: 'text-success',
        badge: 'border-success/50 bg-success-highlight text-success',
    },
    warning: {
        accentLine: 'bg-warning',
        iconContainer: 'border-warning/40 bg-warning-highlight',
        icon: 'text-warning',
        badge: 'border-warning/50 bg-warning-highlight text-warning',
    },
    danger: {
        accentLine: 'bg-danger',
        iconContainer: 'border-danger/40 bg-danger-highlight',
        icon: 'text-danger',
        badge: 'border-danger/50 bg-danger-highlight text-danger',
    },
}

export const PlatformStatusBanner = (): JSX.Element => {
    const { postHogStatusTooltip, postHogStatusBadgeStatus, postHogStatus } = useValues(healthMenuLogic)
    const styles = STATUS_STYLES[postHogStatusBadgeStatus]
    const statusLabel = STATUS_LABELS[postHogStatus]
    const statusMessage = postHogStatusTooltip ?? 'Checking for active incidents...'

    return (
        <div className="max-w-3xl rounded-lg border border-primary bg-surface-primary shadow-sm overflow-hidden">
            <div className={cn('h-1 w-full', styles.accentLine)} />
            <div className="flex flex-col gap-4 p-4 @2xl/main-content:flex-row @2xl/main-content:items-center @2xl/main-content:justify-between">
                <div className="flex items-start gap-3 min-w-0">
                    <div
                        className={cn(
                            'size-10 rounded-full border flex items-center justify-center shrink-0',
                            styles.iconContainer
                        )}
                    >
                        <IconCloud className={cn('size-5', styles.icon)} />
                    </div>
                    <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs uppercase font-semibold tracking-wide text-tertiary">
                                Platform status
                            </span>
                            <span
                                className={cn(
                                    'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
                                    styles.badge
                                )}
                            >
                                {statusLabel}
                            </span>
                        </div>
                        <p className="mt-1 mb-0 text-base font-semibold leading-snug text-primary">{statusMessage}</p>
                    </div>
                </div>
                <LemonButton size="small" type="secondary" to={INCIDENT_IO_STATUS_PAGE_BASE} targetBlank>
                    View status page
                </LemonButton>
            </div>
        </div>
    )
}
