import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import React, { useMemo } from 'react'

import { MaxDashboardContext, MaxInsightContext } from './maxTypes'

interface ContextTagsProps {
    insights?: MaxInsightContext[]
    dashboards?: MaxDashboardContext[]
    useCurrentPageContext?: boolean
    onRemoveInsight?: (key: string | number) => void
    onRemoveDashboard?: (key: string | number) => void
    onDisableCurrentPageContext?: () => void
    className?: string
}

interface ContextSummaryProps {
    insights?: MaxInsightContext[]
    dashboards?: MaxDashboardContext[]
    useCurrentPageContext?: boolean
}

export function ContextSummary({
    insights,
    dashboards,
    useCurrentPageContext,
}: ContextSummaryProps): JSX.Element | null {
    const contextCounts = useMemo(() => {
        const counts = {
            insights: insights ? insights.length : 0,
            dashboards: dashboards ? dashboards.length : 0,
            currentPage: useCurrentPageContext ? 1 : 0,
        }
        return counts
    }, [insights, dashboards, useCurrentPageContext])

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

        return items
    }, [insights, dashboards, useCurrentPageContext])

    if (totalCount === 0) {
        return null
    }

    const tooltipContent = (
        <div className="flex flex-col gap-1 max-w-xs">
            {allItems.map((item, index) => (
                <div key={index} className="flex items-center gap-1">
                    {React.cloneElement(item.icon, { className: 'text-base' })}
                    <span>{item.name}</span>
                </div>
            ))}
        </div>
    )

    return (
        <Tooltip title={tooltipContent} placement="bottom">
            <div className="flex items-center gap-1 text-xs text-muted hover:text-default w-fit select-none mb-1.5">
                <IconPageChart className="text-sm" />
                <span className="italic">With {contextSummaryText}</span>
            </div>
        </Tooltip>
    )
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
    const allTags = useMemo(() => {
        const tags: JSX.Element[] = []

        // Current page context
        if (useCurrentPageContext) {
            tags.push(
                <LemonTag
                    key="current-page"
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

        return tags
    }, [insights, dashboards, useCurrentPageContext, onRemoveInsight, onRemoveDashboard, onDisableCurrentPageContext])

    if (allTags.length === 0) {
        return null
    }

    return <div className={className || 'flex flex-wrap gap-1 w-full min-w-0 overflow-hidden'}>{allTags}</div>
}
