import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'

import { maxContextLogic } from './maxContextLogic'
import { MaxActionContext, MaxDashboardContext, MaxEventContext, MaxInsightContext } from './maxTypes'

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

    const totalCount =
        contextCounts.insights +
        contextCounts.dashboards +
        contextCounts.currentPage +
        contextCounts.events +
        contextCounts.actions

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

export function ContextTags(): JSX.Element | null {
    const { contextInsights, contextDashboards, contextEvents, contextActions, useCurrentPageContext } =
        useValues(maxContextLogic)
    const {
        removeContextInsight,
        removeContextDashboard,
        removeContextEvent,
        removeContextAction,
        disableCurrentPageContext,
    } = useActions(maxContextLogic)

    const allTags = useMemo(() => {
        const tags: JSX.Element[] = []

        // Current page context
        if (useCurrentPageContext) {
            tags.push(
                <LemonTag
                    key="current-page"
                    size="xsmall"
                    icon={<IconPageChart />}
                    onClose={disableCurrentPageContext}
                    closable
                    closeOnClick
                >
                    Current page
                </LemonTag>
            )
        }

        // Dashboards
        if (contextDashboards) {
            contextDashboards.forEach((dashboard: MaxDashboardContext) => {
                const name = dashboard.name || `Dashboard ${dashboard.id}`
                tags.push(
                    <LemonTag
                        key={`dashboard-${dashboard.id}`}
                        size="xsmall"
                        icon={<IconDashboard />}
                        onClose={() => removeContextDashboard(dashboard.id)}
                        closable
                        closeOnClick
                    >
                        {name}
                    </LemonTag>
                )
            })
        }

        // Insights
        if (contextInsights) {
            contextInsights.forEach((insight: MaxInsightContext) => {
                const name = insight.name || `Insight ${insight.id}`
                tags.push(
                    <LemonTag
                        key={`insight-${insight.id}`}
                        size="xsmall"
                        icon={<IconGraph />}
                        onClose={() => removeContextInsight(insight.id)}
                        closable
                        closeOnClick
                    >
                        {name}
                    </LemonTag>
                )
            })
        }

        // Events
        if (contextEvents) {
            contextEvents.forEach((event) => {
                tags.push(
                    <LemonTag
                        key={`event-${event.id}`}
                        size="xsmall"
                        icon={<IconEvent />}
                        onClose={() => removeContextEvent(event.id)}
                        closable
                        closeOnClick
                    >
                        {event.name}
                    </LemonTag>
                )
            })
        }

        // Actions
        if (contextActions) {
            contextActions.forEach((action) => {
                tags.push(
                    <LemonTag
                        key={`action-${action.id}`}
                        size="xsmall"
                        icon={<IconAction />}
                        onClose={() => removeContextAction(action.id)}
                        closable
                        closeOnClick
                    >
                        {action.name || `Action ${action.id}`}
                    </LemonTag>
                )
            })
        }

        return tags
    }, [
        useCurrentPageContext,
        contextDashboards,
        contextInsights,
        contextEvents,
        contextActions,
        removeContextDashboard,
        removeContextInsight,
        removeContextEvent,
        removeContextAction,
        disableCurrentPageContext,
    ])

    if (allTags.length === 0) {
        return null
    }

    return <div className="flex flex-wrap gap-1 flex-1 min-w-0">{allTags}</div>
}

export function ContextDisplay(): JSX.Element {
    const { hasData, contextOptions, taxonomicGroupTypes, mainTaxonomicGroupType } = useValues(maxContextLogic)
    const { handleTaxonomicFilterChange } = useActions(maxContextLogic)

    return (
        <div className="w-full">
            <div className="flex flex-wrap items-start gap-2 w-full">
                <TaxonomicPopover
                    size="xsmall"
                    type="tertiary"
                    className="-mx-1.5 flex-shrink-0"
                    groupType={mainTaxonomicGroupType}
                    groupTypes={taxonomicGroupTypes}
                    onChange={handleTaxonomicFilterChange}
                    placeholder={hasData ? '@' : '@ Add context'}
                    maxContextOptions={contextOptions}
                />
                <ContextTags />
            </div>
        </div>
    )
}
