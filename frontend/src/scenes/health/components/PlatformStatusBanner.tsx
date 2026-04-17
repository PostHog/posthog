import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import type { LemonBannerProps } from '@posthog/lemon-ui'

import { healthMenuLogic } from 'lib/components/HealthMenu/healthMenuLogic'
import type { PostHogStatusBadgeStatus, PostHogStatusType } from 'lib/components/HealthMenu/healthMenuLogic'
import { HeartHog, SleepingHog, WarningHog } from 'lib/components/hedgehogs'

import { INCIDENT_IO_STATUS_PAGE_BASE } from '~/layout/navigation-3000/incident/incidentStatus'

const STATUS_CONFIG: Record<
    PostHogStatusBadgeStatus,
    {
        bannerType: LemonBannerProps['type']
        Hog: (props: React.ImgHTMLAttributes<HTMLImageElement>) => JSX.Element
    }
> = {
    success: { bannerType: 'success', Hog: HeartHog },
    warning: { bannerType: 'warning', Hog: WarningHog },
    danger: { bannerType: 'error', Hog: SleepingHog },
}

const STATUS_LABELS: Record<PostHogStatusType, string> = {
    operational: 'Operational',
    degraded_performance: 'Degraded performance',
    partial_outage: 'Partial outage',
    major_outage: 'Major outage',
}

export const PlatformStatusBanner = (): JSX.Element => {
    const { postHogStatusTooltip, postHogStatusBadgeStatus, postHogStatus } = useValues(healthMenuLogic)
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
                to: INCIDENT_IO_STATUS_PAGE_BASE,
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
