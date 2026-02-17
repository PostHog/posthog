import { useValues } from 'kea'

import { LemonBanner, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { CATEGORY_ORDER, HEALTH_CATEGORY_CONFIG, categoryForKind } from '../healthCategories'
import type { HealthIssueCategory } from '../healthCategories'
import { healthSceneLogic } from '../healthSceneLogic'
import { severityToTagType } from '../healthUtils'
import type { HealthIssue, HealthIssueSeverity } from '../types'
import { HealthIssueCard } from './HealthIssueCard'

const SEVERITY_ORDER: HealthIssueSeverity[] = ['critical', 'warning', 'info']

const worstSeverity = (issues: HealthIssue[]): HealthIssueSeverity => {
    for (const severity of SEVERITY_ORDER) {
        if (issues.some((i) => i.severity === severity)) {
            return severity
        }
    }
    return 'info'
}

export const HealthIssueList = (): JSX.Element => {
    const { issues, healthIssuesLoading, healthIssues } = useValues(healthSceneLogic)

    if (healthIssuesLoading && !healthIssues) {
        return (
            <div className="flex flex-col gap-3">
                <LemonSkeleton className="h-16 rounded" />
                <LemonSkeleton className="h-16 rounded" />
                <LemonSkeleton className="h-16 rounded" />
            </div>
        )
    }

    if (!healthIssuesLoading && healthIssues === null) {
        return (
            <LemonBanner type="warning">Error loading health information. Please try refreshing the page.</LemonBanner>
        )
    }

    if (issues.length === 0) {
        return (
            <LemonBanner type="success">
                <p className="font-semibold mb-0">All systems healthy</p>
                <p className="text-sm mt-1 mb-0">No active health issues found for your project.</p>
            </LemonBanner>
        )
    }

    const groupedByCategory: Partial<Record<HealthIssueCategory, HealthIssue[]>> = {}
    for (const issue of issues) {
        const category = categoryForKind(issue.kind)
        if (!groupedByCategory[category]) {
            groupedByCategory[category] = []
        }
        groupedByCategory[category]!.push(issue)
    }

    const populatedCategories = CATEGORY_ORDER.filter((cat) => groupedByCategory[cat])

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            {populatedCategories.map((category) => {
                const categoryIssues = groupedByCategory[category]!
                const config = HEALTH_CATEGORY_CONFIG[category]
                const worst = worstSeverity(categoryIssues)
                return (
                    <LemonCollapse
                        key={category}
                        defaultActiveKey={category}
                        panels={[
                            {
                                key: category,
                                header: (
                                    <div className="flex items-center justify-between w-full pr-2">
                                        <div className="flex items-center gap-2">
                                            {config.icon}
                                            <span className="font-medium">{config.label}</span>
                                            <span className="text-xs text-muted">({categoryIssues.length})</span>
                                        </div>
                                        <LemonTag type={severityToTagType(worst)} size="small">
                                            {worst}
                                        </LemonTag>
                                    </div>
                                ),
                                content: (
                                    <div className="divide-y divide-border -m-4">
                                        {categoryIssues.map((issue) => (
                                            <HealthIssueCard key={issue.id} issue={issue} />
                                        ))}
                                    </div>
                                ),
                            },
                        ]}
                    />
                )
            })}
        </div>
    )
}
