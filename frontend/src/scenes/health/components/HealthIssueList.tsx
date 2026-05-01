import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CATEGORY_DETAIL_CONFIG } from '../categoryDetail/categoryDetailConfig'
import { CATEGORY_ORDER, HEALTH_CATEGORY_CONFIG, categoryForKind } from '../healthCategories'
import type { HealthIssueCategory } from '../healthCategories'
import { healthSceneLogic } from '../healthSceneLogic'
import { severityToTagType, worstSeverity } from '../healthUtils'
import type { HealthIssue } from '../types'
import { HealthIssueCard } from './HealthIssueCard'

export const HealthIssueList = (): JSX.Element => {
    const { issues, healthIssuesLoading, healthIssues } = useValues(healthSceneLogic)
    const { dismissIssue, undismissIssue } = useActions(healthSceneLogic)

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
        <div className="flex flex-col gap-4">
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
                                        <div className="flex items-center gap-2">
                                            <LemonTag type={severityToTagType(worst)} size="small">
                                                {worst}
                                            </LemonTag>
                                            <LemonButton
                                                type="tertiary"
                                                size="xsmall"
                                                to={
                                                    CATEGORY_DETAIL_CONFIG[category]?.redirectUrl ??
                                                    urls.healthCategory(category)
                                                }
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                View details
                                            </LemonButton>
                                        </div>
                                    </div>
                                ),
                                content: (
                                    <div className="-m-4">
                                        <CategoryContent
                                            category={category}
                                            issues={categoryIssues}
                                            onDismiss={dismissIssue}
                                            onUndismiss={undismissIssue}
                                        />
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

function CategoryContent({
    category,
    issues,
    onDismiss,
    onUndismiss,
}: {
    category: HealthIssueCategory
    issues: HealthIssue[]
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    const TableComponent = CATEGORY_DETAIL_CONFIG[category]?.tableComponent
    if (TableComponent) {
        return <TableComponent issues={issues} onDismiss={onDismiss} onUndismiss={onUndismiss} />
    }
    return (
        <div className="divide-y divide-border">
            {issues.map((issue) => (
                <HealthIssueCard key={issue.id} issue={issue} onDismiss={onDismiss} onUndismiss={onUndismiss} />
            ))}
        </div>
    )
}
