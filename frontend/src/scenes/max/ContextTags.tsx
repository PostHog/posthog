import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'

import { ActionType, DashboardType, EventDefinition, QueryBasedInsightModel } from '~/types'

interface ContextTagsProps {
    insights?: Record<string, Partial<QueryBasedInsightModel>>
    dashboards?: Record<string, DashboardType<QueryBasedInsightModel>>
    events?: Record<string, EventDefinition>
    actions?: Record<string, ActionType>
    useCurrentPageContext?: boolean
    onRemoveInsight?: (key: string) => void
    onRemoveDashboard?: (key: string) => void
    onRemoveEvent?: (key: string) => void
    onRemoveAction?: (key: string) => void
    onDisableCurrentPageContext?: () => void
    className?: string
}

export function ContextTags({
    insights,
    dashboards,
    events,
    actions,
    useCurrentPageContext,
    onRemoveInsight,
    onRemoveDashboard,
    onRemoveEvent,
    onRemoveAction,
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
                    {insight.name || `Insight ${insight.short_id || insight.id}`}
                </LemonTag>
            )
        })
    }

    // Events
    if (events) {
        Object.entries(events).forEach(([key, event]) => {
            tags.push(
                <LemonTag
                    key={`event-${key}`}
                    size="xsmall"
                    icon={<IconEvent />}
                    closable={!!onRemoveEvent}
                    onClose={onRemoveEvent ? () => onRemoveEvent(key) : undefined}
                >
                    {event.name}
                </LemonTag>
            )
        })
    }

    // Actions
    if (actions) {
        Object.entries(actions).forEach(([key, action]) => {
            tags.push(
                <LemonTag
                    key={`action-${key}`}
                    size="xsmall"
                    icon={<IconAction />}
                    closable={!!onRemoveAction}
                    onClose={onRemoveAction ? () => onRemoveAction(key) : undefined}
                >
                    {action.name || `Action ${action.id}`}
                </LemonTag>
            )
        })
    }

    return tags.length > 0 ? <div className={className || 'flex flex-wrap gap-1'}>{tags}</div> : null
}
