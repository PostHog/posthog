import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { HealthCheckSection } from './components/HealthCheckSection'
import { HealthCheck } from './healthCheckTypes'
import { webAnalyticsHealthLogic } from './webAnalyticsHealthLogic'

export function HealthStatusTab(): JSX.Element {
    const { overallHealthStatus, checksByCategory, webAnalyticsHealthStatusLoading, urgentFailedChecks } =
        useValues(webAnalyticsHealthLogic)
    const { refreshHealthChecks } = useActions(webAnalyticsHealthLogic)

    return (
        <div className="mt-4 space-y-4 max-w-4xl">
            {urgentFailedChecks.length > 0 && <UrgentIssuesBanner checks={urgentFailedChecks} />}

            <OverallHealthBanner
                status={overallHealthStatus.status}
                summary={overallHealthStatus.summary}
                passedCount={overallHealthStatus.passedCount}
                totalCount={overallHealthStatus.totalCount}
                onRefresh={refreshHealthChecks}
                loading={webAnalyticsHealthStatusLoading}
            />

            <div className="space-y-3">
                <HealthCheckSection
                    category="events"
                    checks={checksByCategory.events}
                    defaultOpen={checksByCategory.events.some((check: HealthCheck) => check.status !== 'success')}
                />
                <HealthCheckSection
                    category="configuration"
                    checks={checksByCategory.configuration}
                    defaultOpen={checksByCategory.configuration.some(
                        (check: HealthCheck) => check.status !== 'success'
                    )}
                />
                <HealthCheckSection
                    category="performance"
                    checks={checksByCategory.performance}
                    defaultOpen={checksByCategory.performance.some((check: HealthCheck) => check.status !== 'success')}
                />
            </div>
        </div>
    )
}

function UrgentIssuesBanner({ checks }: { checks: HealthCheck[] }): JSX.Element {
    return (
        <LemonBanner type="error">
            <div className="font-semibold">Action required</div>
            <div className="mt-1 space-y-1">
                {checks.map((check) => (
                    <div key={check.id} className="text-sm">
                        <span className="font-bold">{check.title}:</span> {check.description}
                    </div>
                ))}
            </div>
        </LemonBanner>
    )
}

interface OverallHealthBannerProps {
    status: 'success' | 'warning' | 'error' | 'loading'
    summary: string
    passedCount: number
    totalCount: number
    onRefresh: () => void
    loading: boolean
}

function OverallHealthBanner({
    status,
    summary,
    passedCount,
    totalCount,
    onRefresh,
    loading,
}: OverallHealthBannerProps): JSX.Element {
    if (status === 'loading') {
        return (
            <div className="p-4 rounded border border-primary/10 bg-surface-primary">
                <LemonSkeleton className="w-64 h-6 mb-2" />
                <LemonSkeleton className="w-48 h-4" />
            </div>
        )
    }

    const bannerType = status === 'success' ? 'success' : status === 'error' ? 'error' : 'warning'

    return (
        <LemonBanner type={bannerType}>
            <div className="flex items-center justify-between w-full">
                <div>
                    <div className="font-semibold">{summary}</div>
                    <div className="text-sm mt-0.5">
                        {passedCount} of {totalCount} checks passed
                    </div>
                </div>
                <LemonButton type="secondary" size="small" icon={<IconRefresh />} onClick={onRefresh} loading={loading}>
                    Refresh
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
