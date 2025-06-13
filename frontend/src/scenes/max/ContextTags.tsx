import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'

import { MaxActionContext, MaxDashboardContext, MaxEventContext, MaxInsightContext } from './maxTypes'

interface ContextTagsProps {
    insights?: MaxInsightContext[]
    dashboards?: MaxDashboardContext[]
    events?: MaxEventContext[]
    actions?: MaxActionContext[]
    useCurrentPageContext?: boolean
    onRemoveInsight?: (id: string | number) => void
    onRemoveDashboard?: (id: string | number) => void
    onRemoveEvent?: (id: string | number) => void
    onRemoveAction?: (id: string | number) => void
    onDisableCurrentPageContext?: () => void
    className?: string
}

interface ContextSummaryProps {
    insights?: MaxInsightContext[]
    dashboards?: MaxDashboardContext[]
    events?: MaxEventContext[]
    actions?: MaxActionContext[]
    useCurrentPageContext?: boolean
}

export function ContextSummary({
    insights,
    dashboards,
    events,
    actions,
    useCurrentPageContext,
}: ContextSummaryProps): JSX.Element | null {
    const contextCounts = useMemo(() => {
        const counts = {
            insights: insights ? insights.length : 0,
            dashboards: dashboards ? dashboards.length : 0,
            currentPage: useCurrentPageContext ? 1 : 0,
            events: events ? events.length : 0,
            actions: actions ? actions.length : 0,
        }
        return counts
    }, [insights, dashboards, useCurrentPageContext, events, actions])

    const totalCount = contextCounts.insights + contextCounts.dashboards + contextCounts.currentPage

    const contextSummaryText = useMemo(() => {
        const parts = []
        if (contextCounts.currentPage > 0) {
            parts.push('page')
        }
        if (contextCounts.dashboards > 0) {
            parts.push(`${contextCounts.dashboards} dashboard${contextCounts.dashboards > 1 ? 's' : ''}`)
        }
        if (contextCounts.insights > 0) {
            parts.push(`${contextCounts.insights} insight${contextCounts.insights > 1 ? 's' : ''}`)
        }
        if (contextCounts.events > 0) {
            parts.push(`${contextCounts.events} event${contextCounts.events > 1 ? 's' : ''}`)
        }
        if (contextCounts.actions > 0) {
            parts.push(`${contextCounts.actions} action${contextCounts.actions > 1 ? 's' : ''}`)
        }

        if (parts.length === 1) {
            return parts[0]
        }
        if (parts.length === 2) {
            return `${parts[0]} + ${parts[1]}`
        }
        return parts.join(' + ')
    }, [contextCounts])

    const allItems = useMemo(() => {
        const items = []

        if (useCurrentPageContext) {
            items.push({ type: 'current-page', name: 'Current page', icon: <IconPageChart /> })
        }

        if (dashboards) {
            dashboards.forEach((dashboard) => {
                items.push({
                    type: 'dashboard',
                    name: dashboard.name || `Dashboard ${dashboard.id}`,
                    icon: <IconDashboard />,
                })
            })
        }

        if (insights) {
            insights.forEach((insight) => {
                items.push({
                    type: 'insight',
                    name: insight.name || `Insight ${insight.id}`,
                    icon: <IconGraph />,
                })
            })
        }

        if (events) {
            events.forEach((event) => {
                items.push({
                    type: 'event',
                    name: event.name || `Event ${event.id}`,
                    icon: <IconEvent />,
                })
            })
        }

        if (actions) {
            actions.forEach((action) => {
                items.push({
                    type: 'action',
                    name: action.name || `Action ${action.id}`,
                    icon: <IconAction />,
                })
            })
        }

        return items
    }, [useCurrentPageContext, dashboards, insights, events, actions])

    if (totalCount === 0) {
        return null
    }

    const tooltipContent = (
        <div className="flex flex-col gap-1 p-1 max-w-xs">
            {allItems.map((item, index) => (
                <div key={index} className="flex items-center gap-1.5 text-xs">
                    {item.icon}
                    <span>{item.name}</span>
                </div>
            ))}
        </div>
    )

    return (
        <div className="mb-2">
            <Tooltip title={tooltipContent} placement="bottom">
                <div className="flex items-center gap-1.5 text-xs text-muted hover:text-default transition-colors w-fit">
                    <IconPageChart className="text-muted" />
                    <span className="italic">With {contextSummaryText}</span>
                </div>
            </Tooltip>
        </div>
    )
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
    const allTags = useMemo(() => {
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
                    closeOnClick
                >
                    Current page
                </LemonTag>
            )
        }

        // Dashboards
        if (dashboards) {
            dashboards.forEach((dashboard: MaxDashboardContext) => {
                const name = dashboard.name || `Dashboard ${dashboard.id}`
                tags.push(
                    <LemonTag
                        key={`dashboard-${dashboard.id}`}
                        size="xsmall"
                        icon={<IconDashboard />}
                        closable={!!onRemoveDashboard}
                        onClose={onRemoveDashboard ? () => onRemoveDashboard(dashboard.id) : undefined}
                        closeOnClick
                    >
                        {name}
                    </LemonTag>
                )
            })
        }

        // Insights
        if (insights) {
            insights.forEach((insight: MaxInsightContext) => {
                const name = insight.name || `Insight ${insight.id}`
                tags.push(
                    <LemonTag
                        key={`insight-${insight.id}`}
                        size="xsmall"
                        icon={<IconGraph />}
                        closable={!!onRemoveInsight}
                        onClose={onRemoveInsight ? () => onRemoveInsight(insight.id) : undefined}
                        closeOnClick
                    >
                        {name}
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

        return tags
    }, [
        useCurrentPageContext,
        dashboards,
        insights,
        events,
        actions,
        onDisableCurrentPageContext,
        onRemoveDashboard,
        onRemoveInsight,
        onRemoveEvent,
        onRemoveAction,
    ])

    if (allTags.length === 0) {
        return null
    }

    return <div className={className || 'flex flex-wrap gap-1 w-full min-w-0 overflow-hidden'}>{allTags}</div>
}
