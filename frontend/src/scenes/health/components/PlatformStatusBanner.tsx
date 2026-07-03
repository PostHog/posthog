import { useValues } from 'kea'

import { HedgehogDrivingHogzilla } from '@posthog/brand/hoggies'
import { LemonBanner } from '@posthog/lemon-ui'
import type { LemonBannerProps } from '@posthog/lemon-ui'

import { HeartHog, WarningHog } from 'lib/components/hedgehogs'
import { posthogStatusLogic } from 'lib/components/HelpMenu/posthogStatusLogic'
import type { PostHogStatusBadgeStatus, PostHogStatusType } from 'lib/components/HelpMenu/posthogStatusLogic'

const STATUS_CONFIG: Record<
    PostHogStatusBadgeStatus,
    {
        bannerType: LemonBannerProps['type']
        Hog: React.ComponentType<{ className?: string }>
    }
> = {
    success: { bannerType: 'success', Hog: HeartHog },
    warning: { bannerType: 'warning', Hog: WarningHog },
    danger: { bannerType: 'error', Hog: HedgehogDrivingHogzilla },
}

const STATUS_LABELS: Record<PostHogStatusType, string> = {
    operational: 'Operational',
    degraded_performance: 'Degraded performance',
    partial_outage: 'Partial outage',
    major_outage: 'Major outage',
}

export const PlatformStatusBanner = (): JSX.Element => {
    const { postHogStatusTooltip, postHogStatusBadgeStatus, postHogStatus, statusPageUrl } =
        useValues(posthogStatusLogic)
    const { bannerType, Hog } = STATUS_CONFIG[postHogStatusBadgeStatus]
    const statusLabel = STATUS_LABELS[postHogStatus]
    const statusMessage = postHogStatusTooltip ?? 'Checking for active incidents...'

    return (
        <LemonBanner
            type={bannerType}
            icon={<Hog className="size-10 shrink-0" />}
            hideIcon={false}
            action={{
                children: 'View status page',
                to: statusPageUrl,
                targetBlank: true,
            }}
        >
            <div>
                <div className="font-semibold">Platform status: {statusLabel}</div>
                <div className="text-sm mt-0.5">{statusMessage}</div>
            </div>
        </LemonBanner>
    )
}
