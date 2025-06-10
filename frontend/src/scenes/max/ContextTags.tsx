import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useEffect, useMemo, useRef, useState } from 'react'

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

interface TagItem {
    key: string
    element: JSX.Element
    name: string
    type: 'current-page' | 'dashboard' | 'insight'
    onRemove?: () => void
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
    useCurrentPageContext,
    onRemoveInsight,
    onRemoveDashboard,
    onDisableCurrentPageContext,
    className,
}: ContextTagsProps): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement>(null)
    const [visibleTags, setVisibleTags] = useState<TagItem[]>([])
    const [hiddenTags, setHiddenTags] = useState<TagItem[]>([])
    const [, setContainerWidth] = useState(0)

    const allTags: TagItem[] = useMemo(() => {
        const tags: TagItem[] = []

        // Current page context
        if (useCurrentPageContext) {
            tags.push({
                key: 'current-page',
                type: 'current-page',
                name: 'Current page',
                onRemove: onDisableCurrentPageContext,
                element: (
                    <LemonTag
                        key="current-page"
                        size="xsmall"
                        icon={<IconPageChart />}
                        closable={!!onDisableCurrentPageContext}
                        onClose={onDisableCurrentPageContext}
                    >
                        Current page
                    </LemonTag>
                ),
            })
        }

        // Dashboards
        if (dashboards) {
            dashboards.forEach((dashboard: MaxDashboardContext) => {
                const name = dashboard.name || `Dashboard ${dashboard.id}`
                tags.push({
                    key: `dashboard-${dashboard.id}`,
                    type: 'dashboard',
                    name,
                    onRemove: onRemoveDashboard ? () => onRemoveDashboard(dashboard.id) : undefined,
                    element: (
                        <LemonTag
                            key={`dashboard-${dashboard.id}`}
                            size="xsmall"
                            icon={<IconDashboard />}
                            closable={!!onRemoveDashboard}
                            onClose={onRemoveDashboard ? () => onRemoveDashboard(dashboard.id) : undefined}
                        >
                            {name}
                        </LemonTag>
                    ),
                })
            })
        }

        // Insights
        if (insights) {
            insights.forEach((insight: MaxInsightContext) => {
                const name = insight.name || `Insight ${insight.id}`
                tags.push({
                    key: `insight-${insight.id}`,
                    type: 'insight',
                    name,
                    onRemove: onRemoveInsight ? () => onRemoveInsight(insight.id) : undefined,
                    element: (
                        <LemonTag
                            key={`insight-${insight.id}`}
                            size="xsmall"
                            icon={<IconGraph />}
                            closable={!!onRemoveInsight}
                            onClose={onRemoveInsight ? () => onRemoveInsight(insight.id) : undefined}
                        >
                            {name}
                        </LemonTag>
                    ),
                })
            })
        }

        return tags
    }, [insights, dashboards, useCurrentPageContext, onRemoveInsight, onRemoveDashboard, onDisableCurrentPageContext])

    useEffect(() => {
        const calculateVisibleTags = (): void => {
            if (!containerRef.current || allTags.length === 0) {
                setVisibleTags(allTags)
                setHiddenTags([])
                return
            }

            const container = containerRef.current
            const containerWidth = container.offsetWidth
            setContainerWidth(containerWidth)

            // Create temporary elements to measure tag widths
            const tempContainer = document.createElement('div')
            tempContainer.style.position = 'absolute'
            tempContainer.style.visibility = 'hidden'
            tempContainer.style.whiteSpace = 'nowrap'
            tempContainer.className = 'flex gap-1'
            document.body.appendChild(tempContainer)

            let totalWidth = 0
            const gap = 4 // 1 * 4px (gap-1)
            const overflowButtonWidth = 60 // Approximate width of +{number} button
            let visibleCount = 0

            // Always reserve space for overflow button if we have more than 1 tag
            const reservedWidth = allTags.length > 1 ? overflowButtonWidth + gap : 0
            const availableWidth = containerWidth - reservedWidth

            for (let i = 0; i < allTags.length; i++) {
                const tempTag = document.createElement('div')
                tempTag.innerHTML = allTags[i].element.props.children
                tempTag.className = 'text-xs px-1.5 py-0.5 rounded border inline-flex items-center gap-1'
                tempContainer.appendChild(tempTag)

                const tagWidth = tempTag.offsetWidth + gap

                if (totalWidth + tagWidth <= availableWidth) {
                    totalWidth += tagWidth
                    visibleCount++
                } else {
                    break
                }
            }

            // If all tags fit, we don't need the overflow button
            if (visibleCount === allTags.length) {
                visibleCount = allTags.length
            }

            document.body.removeChild(tempContainer)

            setVisibleTags(allTags.slice(0, visibleCount))
            setHiddenTags(allTags.slice(visibleCount))
        }

        calculateVisibleTags()

        let resizeObserver: ResizeObserver | null = null
        if (typeof ResizeObserver !== 'undefined' && containerRef.current) {
            resizeObserver = new ResizeObserver(calculateVisibleTags)
            resizeObserver.observe(containerRef.current)
        }

        return () => resizeObserver?.disconnect()
    }, [allTags])

    if (allTags.length === 0) {
        return null
    }

    const overflowTooltipContent = hiddenTags.length > 0 && (
        <div className="flex flex-col gap-2 p-2 max-w-xs">
            {hiddenTags.map((tag) => (
                <div key={tag.key} className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 text-sm">
                        {tag.type === 'current-page' && <IconPageChart />}
                        {tag.type === 'dashboard' && <IconDashboard />}
                        {tag.type === 'insight' && <IconGraph />}
                        {tag.name}
                    </span>
                    {tag.onRemove && (
                        <LemonButton type="primary" size="xsmall" onClick={tag.onRemove}>
                            Remove
                        </LemonButton>
                    )}
                </div>
            ))}
        </div>
    )

    return (
        <div ref={containerRef} className={className || 'flex items-center gap-1 w-full overflow-hidden'}>
            {visibleTags.map((tag) => tag.element)}
            {hiddenTags.length > 0 && (
                <Tooltip title={overflowTooltipContent} placement="bottom">
                    <LemonTag size="xsmall" icon={<>+</>}>
                        {hiddenTags.length}
                    </LemonTag>
                </Tooltip>
            )}
        </div>
    )
}
