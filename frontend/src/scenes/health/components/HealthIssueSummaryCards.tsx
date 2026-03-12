import { useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { HEALTH_CATEGORY_CONFIG } from '../healthCategories'
import type { HealthIssueCategory } from '../healthCategories'
import { healthSceneLogic } from '../healthSceneLogic'
import type { CategoryHealthSummary, HealthIssueSeverity } from '../types'

export const HealthIssueSummaryCards = (): JSX.Element => {
    const { categorySummaries, healthIssuesLoading, healthIssues } = useValues(healthSceneLogic)

    if (healthIssuesLoading && !healthIssues) {
        return (
            <div className="grid grid-cols-1 @2xl/main-content:grid-cols-3 gap-4 max-w-3xl">
                {Array.from({ length: 3 }, (_, i) => (
                    <LemonSkeleton key={i} className="h-28 rounded" />
                ))}
            </div>
        )
    }

    if (!healthIssuesLoading && healthIssues === null) {
        return <></>
    }

    return (
        <div className="grid grid-cols-1 @2xl/main-content:grid-cols-3 gap-4 max-w-3xl">
            {categorySummaries.map((summary) => (
                <CategoryCard key={summary.category} summary={summary} />
            ))}
        </div>
    )
}

const CategoryCard = ({ summary }: { summary: CategoryHealthSummary }): JSX.Element => {
    const config = HEALTH_CATEGORY_CONFIG[summary.category as HealthIssueCategory]
    const isHealthy = summary.issueCount === 0

    const severityColor = (severity: HealthIssueSeverity): string => {
        switch (severity) {
            case 'critical':
                return 'text-danger'
            case 'warning':
                return 'text-warning'
            case 'info':
                return 'text-muted'
        }
    }

    return (
        <div className="relative flex flex-col gap-2 justify-between border border-primary bg-surface-primary rounded p-4 h-full shadow">
            {!isHealthy && (
                <IconWarning className={`size-5 absolute top-3 right-3 ${severityColor(summary.worstSeverity!)}`} />
            )}
            <div className="flex items-center gap-2">
                <span className="text-primary">{config.icon}</span>
                <h3 className="text-sm font-semibold mb-0">{config.label}</h3>
            </div>
            {isHealthy ? (
                <p className="text-sm text-success flex items-center gap-1 mb-0">
                    <IconCheck className="size-4" />
                    {config.healthyDescription ?? 'No issues'}
                </p>
            ) : (
                <p className={`text-sm mb-0 ${severityColor(summary.worstSeverity!)}`}>
                    {summary.issueCount} {summary.issueCount === 1 ? 'issue' : 'issues'}
                </p>
            )}
        </div>
    )
}
