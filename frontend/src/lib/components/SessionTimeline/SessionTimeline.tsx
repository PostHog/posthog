import { cva } from 'cva'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'

import { Link, Spinner } from '@posthog/lemon-ui'

import { Dayjs } from 'lib/dayjs'
import { useAsyncCallback } from 'lib/hooks/useAsyncCallback'
import { useScrollObserver } from 'lib/hooks/useScrollObserver'
import { IconVerticalAlignCenter } from 'lib/lemon-ui/icons'
import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { ItemCategory, ItemCollector, ItemRenderer, RendererProps, TimelineItem } from './timeline'

const LOADING_DEBOUNCE_OPTIONS = { leading: true, delay: 500 }

export interface SessionTimelineHandle {
    scrollToItem: (itemId: string) => void
}

export interface SessionTimelineProps {
    ref: React.RefObject<SessionTimelineHandle>
    collector: ItemCollector
    selectedItemId?: string
    className?: string
    onTimeClick?: (time: Dayjs) => void
}

export function SessionTimeline({
    ref,
    collector,
    selectedItemId,
    className,
    onTimeClick,
}: SessionTimelineProps): JSX.Element {
    const [items, setItems] = useState<TimelineItem[]>([])
    const [categories, setCategories] = useState<ItemCategory[]>(() => collector.getAllCategories())

    function toggleCategory(category: ItemCategory): void {
        setCategories((prevCategories) => {
            if (prevCategories.includes(category)) {
                return prevCategories.filter((c) => c !== category)
            }
            return [...prevCategories, category]
        })
    }

    const containerRef = useRef<HTMLDivElement | null>(null)

    const scrollToItem = useCallback((uuid: string) => {
        const item = containerRef.current?.querySelector(`[data-item-id="${uuid}"]`)
        if (item) {
            requestAnimationFrame(() => {
                item.scrollIntoView({ behavior: 'instant', block: 'center' })
            })
        }
    }, [])

    const [loadBefore, beforeLoading] = useAsyncCallback(
        () =>
            collector.loadBefore(categories, 25).then(() => {
                const items = collector.collectItems()
                const containerEl = containerRef.current
                const scrollTop = containerEl?.scrollTop || 0
                const scrollHeight = containerEl?.scrollHeight || 0
                setItems(items)
                // Restore scroll position
                requestAnimationFrame(() => {
                    const newScrollHeight = containerEl?.scrollHeight || 0
                    if (containerEl) {
                        containerEl.scrollTop = scrollTop + (newScrollHeight - scrollHeight)
                    }
                })
            }),
        [collector, categories],
        LOADING_DEBOUNCE_OPTIONS
    )

    const [loadAfter, afterLoading] = useAsyncCallback(
        () =>
            collector.loadAfter(categories, 25).then(() => {
                setItems(collector.collectItems())
            }),
        [collector, categories],
        LOADING_DEBOUNCE_OPTIONS
    )

    useEffect(() => {
        collector.clear()
        Promise.all([loadBefore(), loadAfter()]).then(() => {
            const items = collector.collectItems()
            setItems(items)
            selectedItemId && scrollToItem(selectedItemId)
        })
    }, [collector, loadBefore, loadAfter, setItems, scrollToItem, selectedItemId])

    const scrollRefCb = useScrollObserver({
        onScrollTop: () => {
            if (collector.hasBefore(categories)) {
                return loadBefore()
            }
        },
        onScrollBottom: () => {
            if (collector.hasAfter(categories)) {
                return loadAfter()
            }
        },
    })

    useImperativeHandle(ref, () => ({ scrollToItem }))

    return (
        <div className={cn('flex', className)}>
            <div className="flex flex-col justify-between items-center p-1 border-r border-gray-3">
                <div className="flex flex-col items-center gap-2">
                    {collector.getCategories().map((cat) => (
                        <ItemCategoryToggle
                            active={categories.includes(cat)}
                            key={cat}
                            category={cat}
                            onClick={() => toggleCategory(cat)}
                        >
                            {collector.getRenderer(cat)?.categoryIcon}
                        </ItemCategoryToggle>
                    ))}
                </div>
                {items.find((item) => item.id === selectedItemId) && (
                    <ButtonPrimitive
                        tooltip="Scroll to item"
                        tooltipPlacement="right"
                        iconOnly
                        onClick={() => selectedItemId && scrollToItem(selectedItemId)}
                    >
                        <IconVerticalAlignCenter />
                    </ButtonPrimitive>
                )}
            </div>
            <div
                ref={(el) => {
                    scrollRefCb(el)
                    containerRef.current = el
                }}
                className="h-[500px] w-full overflow-y-auto relative"
                style={{ scrollbarGutter: 'stable' }}
            >
                {beforeLoading && (
                    <div className={cn(itemContainer({ selected: false }), 'justify-start')}>
                        <Spinner />
                        <span className="text-secondary">loading...</span>
                    </div>
                )}
                {items.map((item) => {
                    const renderer = collector.getRenderer(item.category)
                    if (!renderer) {
                        return null
                    }
                    return (
                        <SessionTimelineItemContainer
                            renderer={renderer}
                            key={item.id}
                            item={item}
                            selected={item.id === selectedItemId}
                            onTimeClick={onTimeClick}
                        />
                    )
                })}
                {afterLoading && !beforeLoading && (
                    <div className={cn(itemContainer({ selected: false }), 'justify-start')}>
                        <Spinner />
                        <span className="text-secondary">loading...</span>
                    </div>
                )}
            </div>
        </div>
    )
}

const itemContainer = cva({
    base: 'flex justify-between gap-2 items-center px-2 w-full h-[2rem]',
    variants: {
        selected: {
            true: 'bg-[var(--gray-1)] border-1 border-accent',
            false: 'border-b border-[var(--gray-2)]',
        },
    },
})

type SessionTimelineItemContainerProps = RendererProps<TimelineItem> & {
    renderer: ItemRenderer<TimelineItem>
    selected: boolean
    onTimeClick?: (timestamp: Dayjs) => void
}

const SessionTimelineItemContainer = forwardRef<HTMLDivElement, SessionTimelineItemContainerProps>(
    function SessionTimelineItemContainer(
        { renderer, item, selected, onTimeClick }: SessionTimelineItemContainerProps,
        ref
    ): JSX.Element {
        return (
            <div ref={ref} className={itemContainer({ selected })} data-item-id={item.id}>
                <span className="text-xs text-tertiary w-[20px] shrink-0 text-center">
                    <renderer.sourceIcon item={item} />
                </span>
                <span className="text-xs text-tertiary w-[50px] shrink-0 text-center">
                    <Link className="text-tertiary hover:text-accent" onClick={() => onTimeClick?.(item.timestamp)}>
                        {item.timestamp.format('HH:mm:ss')}
                    </Link>
                </span>
                <div className="shrink-0 w-[20px] text-center">{renderer.categoryIcon}</div>
                <div className="flex-grow">
                    <renderer.render item={item} />
                </div>
            </div>
        )
    }
)

const itemCategoryToggle = cva({
    base: 'shrink-0',
    variants: {
        active: {
            true: 'text-accent',
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
            {...props}
        />
    )
}
