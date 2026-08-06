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
        <div className={cn('flex h-full w-full min-w-0 overflow-hidden', className)}>
            <div className="flex shrink-0 flex-col items-center justify-between border-r border-border p-1">
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
                className="SessionTimeline__scroll-container relative h-full min-w-0 flex-1 overflow-y-auto"
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
            true: 'border-1 border-[var(--primary)] bg-fill-selected',
            false: 'border-b border-border',
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
            <span className="text-xs text-muted-foreground">Loading...</span>
        </div>
    )
}

function EmptyTimelineState({ title, description }: { title: string; description?: string }): JSX.Element {
    return (
        <div className="h-full min-h-[160px] w-full flex items-center justify-center px-4">
            <div className="text-center">
                <div className="text-sm text-muted-foreground">{title}</div>
                {description ? <div className="mt-1 text-xs text-subtle-foreground">{description}</div> : null}
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
                'border-r-1 flex h-full w-[96px] shrink-0 items-center gap-1.5 border-border px-2 text-xs text-subtle-foreground',
                onTimeClick ? 'cursor-pointer hover:bg-fill-hover hover:text-[var(--foreground)]' : 'cursor-default'
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
        <div className="border-l-1 h-full w-7 shrink-0 border-border">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive
                        className="flex h-full w-7 items-center justify-center rounded-none text-subtle-foreground outline-none hover:bg-fill-hover hover:text-[var(--foreground)]"
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
                            'flex h-full min-w-0 flex-1 items-center gap-2 pl-2 transition-colors hover:bg-fill-hover',
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
                            <span className="flex shrink-0 items-center justify-center pr-2 text-subtle-foreground">
                                {expanded ? <IconCollapse /> : <IconExpand />}
                            </span>
                        ) : null}
                    </div>
                    <TimelineRowMenu menuItems={rowMenuItems} />
                </div>

                {expanded ? (
                    <div className="w-full border-t border-border bg-fill-expanded">
                        {renderer.renderExpanded ? (
                            <div className="text-xs p-2">
                                <renderer.renderExpanded item={item} sessionId={sessionId} />
                            </div>
                        ) : (
                            <div className="p-2 text-xs text-muted-foreground">No details available</div>
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
                '[&>button:hover]:bg-fill-hover'
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
            true: 'text-[var(--primary)]',
            false: 'text-muted-foreground opacity-50',
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
