import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'
import React from 'react'

import { IconAtSign, IconDashboard, IconGraph, IconPageChart, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'

import { maxContextLogic } from './maxContextLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { MaxActionContext, MaxDashboardContext, MaxEventContext, MaxInsightContext } from './maxTypes'

function pluralize(count: number, word: string): string {
    return `${count} ${word}${count > 1 ? 's' : ''}`
}

interface ContextTagItem {
    type: string
    name: string
    icon: React.ReactElement
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
            parts.push(pluralize(contextCounts.dashboards, 'dashboard'))
        }
        if (contextCounts.insights > 0) {
            parts.push(pluralize(contextCounts.insights, 'insight'))
        }
        if (contextCounts.events > 0) {
            parts.push(pluralize(contextCounts.events, 'event'))
        }
        if (contextCounts.actions > 0) {
            parts.push(pluralize(contextCounts.actions, 'action'))
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
        const items: ContextTagItem[] = []

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
    }, [dashboards, insights, events, actions])

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

export function ContextTags({ size = 'default' }: { size?: 'small' | 'default' }): JSX.Element | null {
    const { contextInsights, contextDashboards, contextEvents, contextActions } = useValues(maxContextLogic)
    const { removeContextInsight, removeContextDashboard, removeContextEvent, removeContextAction } =
        useActions(maxContextLogic)

    const allTags = useMemo(() => {
        const tags: JSX.Element[] = []

        // Context items configuration
        const contextConfigs = [
            {
                items: contextDashboards,
                type: 'dashboard',
                icon: IconDashboard,
                removeAction: removeContextDashboard,
                getName: (item: MaxDashboardContext) => item.name || `Dashboard ${item.id}`,
            },
            {
                items: contextInsights,
                type: 'insight',
                icon: IconGraph,
                removeAction: removeContextInsight,
                getName: (item: MaxInsightContext) => item.name || `Insight ${item.id}`,
            },
            {
                items: contextEvents,
                type: 'event',
                icon: IconEvent,
                removeAction: removeContextEvent,
                getName: (item: MaxEventContext) => item.name,
            },
            {
                items: contextActions,
                type: 'action',
                icon: IconAction,
                removeAction: removeContextAction,
                getName: (item: MaxActionContext) => item.name || `Action ${item.id}`,
            },
        ]

        // Generate tags for each context type
        contextConfigs.forEach(({ items, type, icon: IconComponent, removeAction, getName }) => {
            if (items) {
                items.forEach((item: any) => {
                    const name = getName(item)
                    tags.push(
                        <Tooltip key={`${type}-${item.id}`} title={name}>
                            <LemonTag
                                key={`${type}-${item.id}`}
                                icon={<IconComponent className="flex-shrink-0" />}
                                onClose={() => removeAction(item.id)}
                                closable
                                closeOnClick
                                className={clsx('flex items-center', size === 'small' ? 'max-w-20' : 'max-w-48')}
                            >
                                <span className="truncate min-w-0 flex-1">{name}</span>
                            </LemonTag>
                        </Tooltip>
                    )
                })
            }
        })

        return tags
    }, [
        size,
        contextDashboards,
        contextInsights,
        contextEvents,
        contextActions,
        removeContextDashboard,
        removeContextInsight,
        removeContextEvent,
        removeContextAction,
    ])

    if (allTags.length === 0) {
        return null
    }

    return <div className="flex flex-wrap gap-1 flex-1 min-w-0 overflow-hidden">{allTags}</div>
}

interface ContextDisplayProps {
    size?: 'small' | 'default'
}

export function ContextDisplay({ size = 'default' }: ContextDisplayProps): JSX.Element | null {
    const { deepResearchMode, showContextUI } = useValues(maxThreadLogic)
    const { hasData, contextOptions, taxonomicGroupTypes, mainTaxonomicGroupType } = useValues(maxContextLogic)
    const { handleTaxonomicFilterChange } = useActions(maxContextLogic)

    if (!showContextUI) {
        return null
    }

    return (
        <div className="px-1 w-full">
            <div className="flex flex-wrap items-start gap-1 w-full">
                {deepResearchMode ? (
                    <LemonButton
                        size="xxsmall"
                        type="tertiary"
                        className="flex-shrink-0 border"
                        icon={<IconWarning />}
                        disabledReason="Deep research mode doesn't currently support adding context"
                    >
                        Turn off deep research to add context
                    </LemonButton>
                ) : (
                    <Tooltip title="Add context to help Intelligence answer your question">
                        <TaxonomicPopover
                            size="xxsmall"
                            type="tertiary"
                            className="flex-shrink-0 border"
                            groupType={mainTaxonomicGroupType}
                            groupTypes={taxonomicGroupTypes}
                            onChange={handleTaxonomicFilterChange}
                            icon={<IconAtSign />}
                            placeholder={!hasData ? 'Add context' : null}
                            maxContextOptions={contextOptions}
                            width={450}
                        />
                    </Tooltip>
                )}
                <ContextTags size={size} />
            </div>
        </div>
    )
}
