import './SessionTimeline.scss'

import { cva } from 'cva'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'

import { IconCollapse, IconEllipsis, IconExpand } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { Dayjs } from 'lib/dayjs'
import { useScrollObserver } from 'lib/hooks/useScrollObserver'
import { IconVerticalAlignCenter } from 'lib/lemon-ui/icons'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'

import { ItemCategory, ItemCollector, ItemRenderer, RendererProps, TimelineItem, TimelineMenuItem } from './timeline'
import { useTimelineItemLoading } from './useTimelineItemLoading'

export interface SessionTimelineHandle {
    scrollToItem: (itemId: string) => void
}

export interface SessionTimelineProps {
    collector: ItemCollector
    selectedItemId?: string
    className?: string
    onTimeClick?: (time: Dayjs) => void
}

export const SessionTimeline = forwardRef<SessionTimelineHandle, SessionTimelineProps>(function SessionTimeline(
    { collector, selectedItemId, className, onTimeClick }: SessionTimelineProps,
    ref
): JSX.Element {
    const [activeCategories, setActiveCategories] = useState<ItemCategory[]>(() => collector.getAllCategories())

    const allCategories = useMemo(() => collector.getAllCategories(), [collector])
    const activeCategorySet = useMemo(() => new Set(activeCategories), [activeCategories])

    useEffect(() => {
        setActiveCategories(collector.getAllCategories())
    }, [collector])

    function toggleCategory(category: ItemCategory): void {
        setActiveCategories((prev) => {
            if (prev.includes(category)) {
                return prev.filter((c) => c !== category)
            }
            return [...prev, category]
        })
    }

    const containerRef = useRef<HTMLDivElement | null>(null)

    const scrollToItem = useCallback((uuid: string) => {
        const item = containerRef.current?.querySelector(`[data-item-id="${uuid}"]`)
        if (item) {
            requestAnimationFrame(() => {
                item.scrollIntoView({ behavior: 'auto', block: 'center' })
            })
        }
    }, [])

    const { items, loading, scrollLoading, handleScrollTop, handleScrollBottom } = useTimelineItemLoading({
        collector,
        selectedItemId,
        activeCategorySet,
        containerRef,
        scrollToItem,
    })

    const filteredItems = useMemo(
        () => items.filter((item) => activeCategorySet.has(item.category)),
        [items, activeCategorySet]
    )

    const scrollRefCb = useScrollObserver({
        onScrollTop: handleScrollTop,
        onScrollBottom: handleScrollBottom,
    })
    const setContainerRef = useCallback(
        (el: HTMLDivElement | null) => {
            scrollRefCb(el)
            containerRef.current = el
        },
        [scrollRefCb]
    )

    useImperativeHandle(ref, () => ({ scrollToItem }))

    const isLoading = loading || scrollLoading !== null
    const showInitialLoadingRow = loading && items.length === 0
    const hasVisibleSelectedItem = useMemo(
        () => Boolean(selectedItemId && filteredItems.some((item) => item.id === selectedItemId)),
        [filteredItems, selectedItemId]
    )
    const emptyState = useMemo(() => {
        if (activeCategories.length === 0) {
            return {
                title: 'No categories selected',
                description: 'Select at least one category from the left to show timeline items.',
            }
        }

        if (items.length === 0) {
            return {
                title: 'No items',
                description: 'No timeline items were found for this session window.',
            }
        }

        return {
            title: 'No items in selected categories',
            description: 'Try enabling more categories to see additional events.',
        }
    }, [activeCategories.length, items.length])

    return (
        <div className={cn('flex h-full', className)}>
            <div className="flex flex-col justify-between items-center p-1 border-r border-gray-3 shrink-0">
                <CategoryToggleGroup>
                    {allCategories.map((cat) => (
                        <ItemCategoryToggle
                            active={activeCategories.includes(cat)}
                            key={cat}
                            category={cat}
                            onClick={() => toggleCategory(cat)}
                        >
                            {collector.getRenderer(cat)?.categoryIcon}
                        </ItemCategoryToggle>
                    ))}
                </CategoryToggleGroup>
                {hasVisibleSelectedItem && (
                    <ButtonPrimitive
                        tooltip="Scroll to item"
                        tooltipPlacement="right"
                        iconOnly
                        size="xs"
                        onClick={() => selectedItemId && scrollToItem(selectedItemId)}
                    >
                        <IconVerticalAlignCenter />
                    </ButtonPrimitive>
                )}
            </div>
            <div
                ref={setContainerRef}
                data-attr="session-timeline-scroll-container"
                className="SessionTimeline__scroll-container h-full w-full overflow-y-auto relative"
                style={{ scrollbarGutter: 'stable both-edges' }}
            >
                <div className="pr-3">
                    {(showInitialLoadingRow || scrollLoading === 'before') && <LoadingRow />}
                    {filteredItems.map((item) => {
                        const renderer = collector.getRenderer(item.category)
                        if (!renderer) {
                            return null
                        }
                        return (
                            <SessionTimelineItemContainer
                                renderer={renderer}
                                key={item.id}
                                item={item}
                                sessionId={collector.sessionId}
                                selected={item.id === selectedItemId}
                                onTimeClick={onTimeClick}
                            />
                        )
                    })}
                    {!loading && scrollLoading === 'after' && <LoadingRow />}
                    {!isLoading && filteredItems.length === 0 && (
                        <EmptyTimelineState title={emptyState.title} description={emptyState.description} />
                    )}
                </div>
            </div>
        </div>
    )
})

const itemContainer = cva({
    base: 'w-full',
    variants: {
        selected: {
            true: 'bg-[var(--gray-1)] border-1 border-accent',
            false: 'border-b border-[var(--gray-2)]',
        },
    },
})

function getCategoryTooltip(category: ItemCategory): string {
    switch (category) {
        case ItemCategory.ERROR_TRACKING:
            return 'Exception'
        case ItemCategory.EXCEPTION_STEPS:
            return 'Exception step'
        case ItemCategory.CUSTOM_EVENTS:
            return 'Custom event'
        case ItemCategory.PAGE_VIEWS:
            return 'Page view'
        case ItemCategory.CONSOLE_LOGS:
            return 'Console log'
    }
}

function LoadingRow(): JSX.Element {
    return (
        <div className={cn(itemContainer({ selected: false }), 'flex items-center gap-2 px-2 h-[2rem]')}>
            <Spinner />
            <span className="text-secondary text-xs">Loading...</span>
        </div>
    )
}

function EmptyTimelineState({ title, description }: { title: string; description?: string }): JSX.Element {
    return (
        <div className="h-full min-h-[160px] w-full flex items-center justify-center px-4">
            <div className="text-center">
                <div className="text-sm text-secondary">{title}</div>
                {description ? <div className="text-xs text-tertiary mt-1">{description}</div> : null}
            </div>
        </div>
    )
}

function TimelineTimestampCell({
    item,
    onTimeClick,
    SourceIcon,
}: {
    item: TimelineItem
    onTimeClick?: (timestamp: Dayjs) => void
    SourceIcon: React.FC<RendererProps<TimelineItem>>
}): JSX.Element {
    return (
        <button
            type="button"
            disabled={!onTimeClick}
            className={cn(
                'border-r-1 shrink-0 w-[96px] h-full flex items-center gap-1.5 px-2 text-xs text-tertiary',
                onTimeClick ? 'cursor-pointer hover:bg-fill-button-tertiary-hover hover:text-primary' : 'cursor-default'
            )}
            onClick={() => onTimeClick?.(item.timestamp)}
            aria-label={`Open recording at ${item.timestamp.format('HH:mm:ss')}`}
        >
            <span className="w-[16px] shrink-0 flex items-center justify-center">
                <SourceIcon item={item} />
            </span>
            <span className="whitespace-nowrap">{item.timestamp.format('HH:mm:ss')}</span>
        </button>
    )
}

function TimelineRowMenu({ menuItems }: { menuItems: TimelineMenuItem[] }): JSX.Element | null {
    if (menuItems.length === 0) {
        return null
    }

    return (
        <div className="border-l-1 shrink-0 w-7 h-full">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive
                        className="h-full w-7 rounded-none outline-none text-tertiary hover:text-primary hover:bg-fill-button-tertiary-hover flex items-center justify-center"
                        aria-label="More actions"
                        data-attr="session-timeline-row-more"
                    >
                        <IconEllipsis />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>
                <DropdownMenuContent loop align="end" side="bottom" className="p-1 min-w-44">
                    {menuItems.map((menuItem) => (
                        <DropdownMenuItem key={menuItem.key} asChild>
                            <ButtonPrimitive menuItem className="whitespace-nowrap" onClick={menuItem.onClick}>
                                {menuItem.label}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}

type SessionTimelineItemContainerProps = RendererProps<TimelineItem> & {
    renderer: ItemRenderer<TimelineItem>
    selected: boolean
    onTimeClick?: (timestamp: Dayjs) => void
}

const SessionTimelineItemContainer = forwardRef<HTMLDivElement, SessionTimelineItemContainerProps>(
    function SessionTimelineItemContainer(
        { renderer, item, sessionId, selected, onTimeClick }: SessionTimelineItemContainerProps,
        ref
    ): JSX.Element {
        const [expanded, setExpanded] = useState(false)
        const canExpand = Boolean(renderer.renderExpanded)
        const rowMenuItems = renderer.getMenuItems?.({ item, sessionId }) ?? []
        const toggleExpanded = (): void => {
            if (!canExpand) {
                return
            }

            setExpanded((value) => !value)
        }

        const handleExpandKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
            if (!canExpand) {
                return
            }

            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                toggleExpanded()
            }
        }

        return (
            <div ref={ref} className={itemContainer({ selected })} data-item-id={item.id}>
                <div className="flex justify-between pr-0 w-full h-[2rem] items-center">
                    <TimelineTimestampCell item={item} onTimeClick={onTimeClick} SourceIcon={renderer.sourceIcon} />
                    <div
                        className={cn(
                            'flex items-center gap-2 flex-1 min-w-0 h-full pl-2 transition-colors hover:bg-fill-button-tertiary-hover',
                            canExpand && 'cursor-pointer'
                        )}
                        onClick={toggleExpanded}
                        onKeyDown={handleExpandKeyDown}
                        role={canExpand ? 'button' : undefined}
                        tabIndex={canExpand ? 0 : undefined}
                        aria-expanded={canExpand ? expanded : undefined}
                    >
                        <div className="shrink-0 w-[20px] text-center" title={getCategoryTooltip(item.category)}>
                            {renderer.categoryIcon}
                        </div>
                        <div className="flex-grow min-w-0">
                            <renderer.render item={item} sessionId={sessionId} />
                        </div>
                        {canExpand ? (
                            <span className="shrink-0 pr-2 text-tertiary flex items-center justify-center">
                                {expanded ? <IconCollapse /> : <IconExpand />}
                            </span>
                        ) : null}
                    </div>
                    <TimelineRowMenu menuItems={rowMenuItems} />
                </div>

                {expanded ? (
                    <div className="w-full border-t border-border bg-surface-secondary">
                        {renderer.renderExpanded ? (
                            <div className="text-xs p-2">
                                <renderer.renderExpanded item={item} sessionId={sessionId} />
                            </div>
                        ) : (
                            <div className="text-xs p-2 text-secondary">No details available</div>
                        )}
                    </div>
                ) : null}
            </div>
        )
    }
)

function CategoryToggleGroup({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-col gap-0.5',
                '[&>button]:rounded [&>button]:border-0 [&>button]:px-2 [&>button]:py-1.5',
                '[&>button:hover]:bg-fill-button-tertiary-hover'
            )}
        >
            {children}
        </div>
    )
}

const itemCategoryToggle = cva({
    base: 'shrink-0 transition-colors',
    variants: {
        active: {
            true: 'text-accent',
            false: 'text-muted opacity-50',
        },
    },
})

export function ItemCategoryToggle({
    active,
    category,
    ...props
}: ButtonPrimitiveProps & { category: ItemCategory }): JSX.Element {
    return (
        <ButtonPrimitive
            iconOnly
            tooltip={active ? `Hide ${category}` : `Show ${category}`}
            tooltipPlacement="right"
            className={itemCategoryToggle({ active })}
            data-attr={`session-timeline-category-toggle-${category.replaceAll(' ', '-')}`}
            {...props}
        />
    )
}
