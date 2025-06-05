import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { MultiDashboardContextContainer, MultiInsightContextContainer } from './maxTypes'

interface ContextTagsProps {
    insights?: MultiInsightContextContainer
    dashboards?: MultiDashboardContextContainer
    useCurrentPageContext?: boolean
    onRemoveInsight?: (key: string) => void
    onRemoveDashboard?: (key: string) => void
    onDisableCurrentPageContext?: () => void
    className?: string
}

export function ContextTags({
    insights,
    dashboards,
    useCurrentPageContext,
    onRemoveInsight,
    onRemoveDashboard,
    onDisableCurrentPageContext,
    className,
}: ContextTagsProps): JSX.Element | null {
    const tags: JSX.Element[] = []

    // Current page context
    if (useCurrentPageContext) {
        tags.push(
            <LemonTag
                key="current-page"
                size="xsmall"
                icon={<IconPageChart />}
                closable={!!onDisableCurrentPageContext}
                onClose={onDisableCurrentPageContext}
            >
                Current page
            </LemonTag>
        )
    }

    // Dashboards
    if (dashboards) {
        Object.entries(dashboards).forEach(([key, dashboard]) => {
            tags.push(
                <LemonTag
                    key={`dashboard-${key}`}
                    size="xsmall"
                    icon={<IconDashboard />}
                    closable={!!onRemoveDashboard}
                    onClose={onRemoveDashboard ? () => onRemoveDashboard(key) : undefined}
                >
                    {dashboard.name || `Dashboard ${dashboard.id}`}
                </LemonTag>
            )
        })
    }

    // Insights
    if (insights) {
        Object.entries(insights).forEach(([key, insight]) => {
            tags.push(
                <LemonTag
                    key={`insight-${key}`}
                    size="xsmall"
                    icon={<IconGraph />}
                    closable={!!onRemoveInsight}
                    onClose={onRemoveInsight ? () => onRemoveInsight(key) : undefined}
                >
                    {insight.name || `Insight ${insight.id}`}
                </LemonTag>
            )
        })
    }

    return tags.length > 0 ? <div className={className || 'flex flex-wrap gap-1'}>{tags}</div> : null
}
