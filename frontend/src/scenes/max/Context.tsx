import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'
import React from 'react'

import { IconAtSign, IconDashboard, IconGraph, IconPageChart, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { ModeSelector } from './components/ModeSelector'
import { ContextTagItemData, maxContextLogic } from './maxContextLogic'
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

const CONTEXT_TAG_ICONS: Record<ContextTagItemData['type'], React.ComponentType<{ className?: string }>> = {
    dashboard: IconDashboard,
    insight: IconGraph,
    event: IconEvent,
    action: IconAction,
}

export function ContextTags({
    size = 'default',
    inline = false,
}: {
    size?: 'small' | 'default'
    inline?: boolean
}): JSX.Element | null {
    const { contextTagItems } = useValues(maxContextLogic) as { contextTagItems: ContextTagItemData[] }
    const { removeContextInsight, removeContextDashboard, removeContextEvent, removeContextAction } =
        useActions(maxContextLogic)

    const removeActions: Record<ContextTagItemData['type'], (id: string | number) => void> = {
        dashboard: removeContextDashboard,
        insight: removeContextInsight,
        event: removeContextEvent,
        action: removeContextAction,
    }

    if (contextTagItems.length === 0) {
        return null
    }

    return (
        <div
            className={cn(
                'flex flex-wrap gap-1 overflow-hidden',
                inline ? 'inline-flex flex-wrap gap-1 self-start' : 'flex-1 min-w-0'
            )}
        >
            {contextTagItems.map((item: ContextTagItemData) => {
                const IconComponent = CONTEXT_TAG_ICONS[item.type]
                const removeAction = removeActions[item.type]
                return (
                    <Tooltip key={`${item.type}-${item.id}`} title={item.name}>
                        <LemonTag
                            icon={<IconComponent className="flex-shrink-0" />}
                            onClose={() => removeAction(item.id)}
                            closable
                            closeOnClick
                            className={clsx(
                                'flex items-center text-secondary',
                                inline ? 'max-w-none' : size === 'small' ? 'max-w-20' : 'max-w-48'
                            )}
                        >
                            <span className="truncate min-w-0 flex-1">{item.name}</span>
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}

export function ContextToolInfoTags({ size = 'default' }: { size?: 'small' | 'default' }): JSX.Element | null {
    const { toolContextItems } = useValues(maxContextLogic)

    if (toolContextItems.length === 0) {
        return null
    }

    const tooltipContent =
        toolContextItems.length === 1 ? (
            'This context is auto-included from the current view'
        ) : (
            <div className="flex flex-col gap-1">
                <div className="text-xs font-semibold mb-1">This context is auto-included from the current view:</div>
                {toolContextItems.map((item, index) => (
                    <div key={index} className="flex items-center gap-1.5">
                        {item.icon}
                        <span>{item.text}</span>
                    </div>
                ))}
            </div>
        )

    return (
        <Tooltip title={tooltipContent}>
            <LemonTag
                icon={toolContextItems[0].icon}
                className={clsx(
                    'flex items-center cursor-default border-dashed text-secondary',
                    size === 'small' ? 'max-w-20' : 'max-w-48'
                )}
            >
                <span className="truncate min-w-0 flex-1">
                    {toolContextItems[0].text}
                    {toolContextItems.length > 1 && <span className="ml-1">+{toolContextItems.length - 1}</span>}
                </span>
            </LemonTag>
        </Tooltip>
    )
}

interface ContextDisplayProps {
    size?: 'small' | 'default'
}

export function ContextDisplay({ size = 'default' }: ContextDisplayProps): JSX.Element | null {
    const { deepResearchMode, showContextUI, contextDisabledReason } = useValues(maxThreadLogic)
    const { hasData, contextOptions, taxonomicGroupTypes, mainTaxonomicGroupType, toolContextItems } =
        useValues(maxContextLogic)
    const { handleTaxonomicFilterChange } = useActions(maxContextLogic)

    if (!showContextUI) {
        return null
    }

    const hasToolContext = toolContextItems.length > 0

    return (
        <div className="px-2 w-full">
            <div className="flex flex-wrap items-start gap-1 w-full">
                <ModeSelector />
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
                    <Tooltip title={contextDisabledReason ?? 'Add context to help PostHog AI answer your question'}>
                        <TaxonomicPopover
                            size="xxsmall"
                            type="tertiary"
                            className="flex-shrink-0 border"
                            groupType={mainTaxonomicGroupType}
                            groupTypes={taxonomicGroupTypes}
                            onChange={handleTaxonomicFilterChange}
                            icon={<IconAtSign className="text-secondary" />}
                            placeholder={!hasData && !hasToolContext ? 'Add context' : null}
                            placeholderClass="text-secondary"
                            maxContextOptions={contextOptions}
                            width={450}
                            disabledReason={contextDisabledReason}
                        />
                    </Tooltip>
                )}
                <ContextToolInfoTags size={size} />
                <ContextTags size={size} />
            </div>
        </div>
    )
}
