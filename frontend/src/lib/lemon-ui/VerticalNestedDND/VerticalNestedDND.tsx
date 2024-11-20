import './styles.scss'

import {
    closestCenter,
    CollisionDetection,
    defaultDropAnimationSideEffects,
    DndContext,
    DraggableSyntheticListeners,
    DragOverlay,
    DropAnimation,
    getFirstCollision,
    MeasuringStrategy,
    MouseSensor,
    pointerWithin,
    rectIntersection,
    TouchSensor,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import type { UniqueIdentifier } from '@dnd-kit/core/dist/types'
import {
    AnimateLayoutChanges,
    arrayMove,
    defaultAnimateLayoutChanges,
    SortableContext,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import type { Transform } from '@dnd-kit/utilities'
import { CSS } from '@dnd-kit/utilities'
import { IconBuilding, IconTrash } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import debounce from 'lodash.debounce'
import isEqual from 'lodash.isequal'
import React, { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal, unstable_batchedUpdates } from 'react-dom'
export interface VDNDChildItem {
    id: UniqueIdentifier
}

export interface VNDNDContainerItem<T extends VDNDChildItem> {
    items: T[]
    id: UniqueIdentifier
}

export interface VerticalNestedDNDProps<ChildItem extends VDNDChildItem, Item extends VNDNDContainerItem<ChildItem>> {
    initialItems: Item[]
    renderContainerItem: (item: Item) => JSX.Element | null
    renderChildItem: (item: ChildItem) => JSX.Element | null
    createNewContainerItem(): Item
    createNewChildItem(): ChildItem
    onChange?(items: Item[]): void
}

export function VerticalNestedDND<ChildItem extends VDNDChildItem, Item extends VNDNDContainerItem<ChildItem>>({
    initialItems,
    renderContainerItem,
    renderChildItem,
    createNewChildItem,
    createNewContainerItem,
    onChange,
}: VerticalNestedDNDProps<ChildItem, Item>): JSX.Element {
    const [items, setItems] = useState(() => {
        const items: Record<UniqueIdentifier, Item> = {}
        initialItems.forEach((item) => {
            items[item.id] = item
        })
        return items
    })
    const [clonedItems, setClonedItems] = useState<Record<UniqueIdentifier, Item> | null>(null)

    const handle = true

    const [containers, setContainers] = useState(Object.keys(items) as UniqueIdentifier[])
    const [activeId, setActiveId] = useState<UniqueIdentifier | null>(null)
    const lastOverId = useRef<UniqueIdentifier | null>(null)
    const recentlyMovedToNewContainer = useRef(false)
    const sensors = useSensors(useSensor(MouseSensor), useSensor(TouchSensor))
    const isSortingContainer = activeId ? containers.includes(activeId) : false

    const debouncedOnChanged = useMemo(
        () => (onChange ? debounce(onChange, 200, { trailing: true }) : undefined),
        [onChange]
    )
    const savedChanges = useRef<Item[]>(initialItems)
    useEffect(() => {
        const newItemsArray = containers.map((containerId) => items[containerId])
        if (!isEqual(newItemsArray, savedChanges.current)) {
            savedChanges.current = newItemsArray
            debouncedOnChanged?.(newItemsArray)
        }
    }, [containers, items, debouncedOnChanged])

    const collisionDetectionStrategy: CollisionDetection = useCallback(
        (args) => {
            if (activeId && activeId in items) {
                return closestCenter({
                    ...args,
                    droppableContainers: args.droppableContainers.filter((container) => container.id in items),
                })
            }

            // Start by finding any intersecting droppable
            const pointerIntersections = pointerWithin(args)
            const intersections =
                pointerIntersections.length > 0
                    ? // If there are droppables intersecting with the pointer, return those
                      pointerIntersections
                    : rectIntersection(args)
            let overId = getFirstCollision(intersections, 'id')

            if (overId != null) {
                if (overId in items) {
                    const containerItems = items[overId].items

                    // If a container is matched and it contains items (columns 'A', 'B', 'C')
                    if (containerItems.length > 0) {
                        // Return the closest droppable within that container
                        overId = closestCenter({
                            ...args,
                            droppableContainers: args.droppableContainers.filter(
                                (container) =>
                                    container.id !== overId &&
                                    containerItems.some((ChildItem) => ChildItem.id === container.id)
                            ),
                        })[0]?.id
                    }
                }

                lastOverId.current = overId

                return [{ id: overId }]
            }

            // When a draggable item moves to a new container, the layout may shift
            // and the `overId` may become `null`. We manually set the cached `lastOverId`
            // to the id of the draggable item that was moved to the new container, otherwise
            // the previous `overId` will be returned which can cause items to incorrectly shift positions
            if (recentlyMovedToNewContainer.current) {
                lastOverId.current = activeId
            }

            // If no droppable is matched, return the last match
            return lastOverId.current ? [{ id: lastOverId.current }] : []
        },
        [activeId, items]
    )
    const findContainer = (id: UniqueIdentifier): UniqueIdentifier | undefined => {
        if (id in items) {
            return id
        }

        return Object.keys(items).find((key) => items[key].items.some((item) => item.id === id))
    }

    const findChildItem = (id: UniqueIdentifier): ChildItem | undefined => {
        for (const containerId in items) {
            const item = items[containerId].items.find((item) => item.id === id)
            if (item) {
                return item
            }
        }
    }

    const getIndex = (id: UniqueIdentifier): number => {
        const container = findContainer(id)

        if (!container) {
            return -1
        }

        return items[container].items.findIndex((ChildItem) => ChildItem.id === id)
    }

    const onDragCancel = (): void => {
        if (clonedItems) {
            // Reset items to their original state in case items have been
            // Dragged across containers
            setItems(clonedItems)
        }

        setActiveId(null)
        setClonedItems(null)
    }

    useEffect(() => {
        requestAnimationFrame(() => {
            recentlyMovedToNewContainer.current = false
        })
    }, [items])

    return (
        <DndContext
            sensors={sensors}
            collisionDetection={collisionDetectionStrategy}
            measuring={{
                droppable: {
                    strategy: MeasuringStrategy.Always,
                },
            }}
            onDragStart={({ active }) => {
                setActiveId(active.id)
                setClonedItems(items)
            }}
            onDragOver={({ active, over }) => {
                const overId = over?.id
                const activeIsContainer = active.id in items

                if (overId == null) {
                    return
                }

                if (activeIsContainer) {
                    const overContainerId = findContainer(overId)
                    if (!overContainerId) {
                        return
                    }
                    if (activeId !== overContainerId) {
                        setContainers((containers) => {
                            const activeIndex = containers.indexOf(active.id)
                            const overIndex = containers.indexOf(overContainerId)

                            return arrayMove(containers, activeIndex, overIndex)
                        })
                    }
                } else {
                    const overContainerId = findContainer(overId)
                    const activeContainerId = findContainer(active.id)

                    if (!overContainerId || !activeContainerId) {
                        return
                    }
                    const activeContainer = items[activeContainerId]
                    const overContainer = items[overContainerId]

                    if (activeContainerId !== overContainerId) {
                        setItems((items) => {
                            const activeItems = items[activeContainerId].items
                            const overItems = items[overContainerId].items
                            const overIndex = overItems.findIndex((ChildItem) => ChildItem.id === overId)
                            const activeIndex = activeItems.findIndex((ChildItem) => ChildItem.id === active.id)

                            let newIndex: number
                            if (overId in items) {
                                newIndex = overItems.length + 1
                            } else {
                                const isBelowOverItem =
                                    over &&
                                    active.rect.current.translated &&
                                    active.rect.current.translated.top > over.rect.top + over.rect.height

                                const modifier = isBelowOverItem ? 1 : 0

                                newIndex = overIndex >= 0 ? overIndex + modifier : overItems.length + 1
                            }

                            recentlyMovedToNewContainer.current = true

                            const newActiveContainer = {
                                ...activeContainer,
                                items: activeItems.filter((item) => item.id !== active.id),
                            }
                            const newOverContainer = {
                                ...overContainer,
                                items: [
                                    ...overItems.slice(0, newIndex),
                                    activeContainer.items[activeIndex],
                                    ...overItems.slice(newIndex, overItems.length),
                                ],
                            }

                            return {
                                ...items,
                                [activeContainerId]: newActiveContainer,
                                [overContainerId]: newOverContainer,
                            }
                        })
                    } else if (overId !== active.id) {
                        setItems((items) => {
                            const overItems = items[overContainerId].items
                            const overIndex = overItems.findIndex((ChildItem) => ChildItem.id === overId)
                            const activeIndex = overItems.findIndex((ChildItem) => ChildItem.id === active.id)

                            const isBelowOverItem =
                                over &&
                                active.rect.current.translated &&
                                active.rect.current.translated.top > over.rect.top + over.rect.height

                            const modifier = isBelowOverItem ? 1 : 0

                            const newItems = arrayMove(overItems, activeIndex, overIndex + modifier)
                            const newOverContainer = {
                                ...overContainer,
                                items: newItems,
                            }
                            return {
                                ...items,
                                [overContainerId]: newOverContainer,
                            }
                        })
                    }
                }
            }}
            onDragEnd={({ active, over }) => {
                if (active.id in items && over?.id) {
                    setContainers((containers) => {
                        const activeIndex = containers.indexOf(active.id)
                        const overIndex = containers.indexOf(over.id)

                        return arrayMove(containers, activeIndex, overIndex)
                    })
                }

                const activeContainerId = findContainer(active.id)

                if (!activeContainerId) {
                    setActiveId(null)
                    return
                }

                const overId = over?.id

                if (overId == null) {
                    setActiveId(null)
                    return
                }

                const overContainerId = findContainer(overId)

                if (overContainerId) {
                    const activeIndex = items[activeContainerId].items.findIndex(
                        (ChildItem) => ChildItem.id === active.id
                    )
                    const overIndex = items[overContainerId].items.findIndex((ChildItem) => ChildItem.id === overId)

                    if (activeIndex !== overIndex) {
                        setItems((items) => {
                            const newOverContainer = {
                                ...items[overContainerId],
                                items: arrayMove(items[overContainerId].items, activeIndex, overIndex),
                            }
                            return {
                                ...items,
                                [overContainerId]: newOverContainer,
                            }
                        })
                    }
                }

                setActiveId(null)
            }}
            onDragCancel={onDragCancel}
        >
            <div className="space-y-2">
                <SortableContext items={containers} strategy={verticalListSortingStrategy}>
                    {containers.map((containerId) => (
                        <DroppableContainer
                            key={containerId}
                            items={items[containerId].items}
                            onRemove={() => handleRemove(containerId)}
                            renderContainerItem={renderContainerItem}
                            containerItemId={containerId}
                            item={items[containerId]}
                            onAddChild={handleAddChild}
                        >
                            <SortableContext items={items[containerId].items} strategy={verticalListSortingStrategy}>
                                {items[containerId].items.map((value, index) => {
                                    return (
                                        <SortableItem
                                            disabled={isSortingContainer}
                                            key={value.id}
                                            id={value.id}
                                            index={index}
                                            handle={handle}
                                            containerId={containerId}
                                            getIndex={getIndex}
                                            renderChildItem={renderChildItem}
                                            item={value}
                                        />
                                    )
                                })}
                            </SortableContext>
                        </DroppableContainer>
                    ))}
                </SortableContext>
                <div className="px-[calc(1.5rem+1px)]">
                    <LemonButton onClick={handleAddColumn} fullWidth={false} type="secondary">
                        Add container
                    </LemonButton>
                </div>
            </div>
            {createPortal(
                <DragOverlay dropAnimation={dropAnimation}>
                    {activeId
                        ? containers.includes(activeId)
                            ? renderContainerDragOverlay(activeId)
                            : renderSortableItemDragOverlay(activeId)
                        : null}
                </DragOverlay>,
                document.body
            )}
        </DndContext>
    )

    function renderSortableItemDragOverlay(id: UniqueIdentifier): JSX.Element | null {
        const item = findChildItem(id)
        if (!item) {
            return null
        }
        return <ChildItem childItemId={id} dragOverlay renderChildItem={renderChildItem} item={item} />
    }

    function renderContainerDragOverlay(containerId: UniqueIdentifier): JSX.Element | null {
        const item = items[containerId]
        if (!item) {
            return null
        }
        return (
            <Container
                containerItemId={containerId}
                shadow
                renderContainerItem={renderContainerItem}
                item={item}
                onAddChild={() => {}}
            >
                {items[containerId].items.map((item) => (
                    <ChildItem key={item.id} childItemId={item.id} renderChildItem={renderChildItem} item={item} />
                ))}
            </Container>
        )
    }

    function handleRemove(containerID: UniqueIdentifier): void {
        setContainers((containers) => containers.filter((id) => id !== containerID))
    }

    function handleAddColumn(): void {
        const newItem: Item = createNewContainerItem()

        unstable_batchedUpdates(() => {
            setContainers((containers) => [...containers, newItem.id])
            setItems((items) => ({
                ...items,
                [newItem.id]: newItem,
            }))
        })
    }

    function handleAddChild(containerId: UniqueIdentifier): void {
        const newChild = createNewChildItem()

        setItems((items) => {
            const container = items[containerId]
            return {
                ...items,
                [containerId]: {
                    ...container,
                    items: [...container.items, newChild],
                },
            }
        })
    }
}

const dropAnimation: DropAnimation = {
    sideEffects: defaultDropAnimationSideEffects({
        styles: {
            active: {
                opacity: '0.4',
            },
        },
    }),
}
const animateLayoutChanges: AnimateLayoutChanges = (args) => defaultAnimateLayoutChanges({ ...args, wasDragging: true })

interface SortableItemProps<Item extends VDNDChildItem> {
    containerId: UniqueIdentifier
    id: UniqueIdentifier
    index: number
    handle: boolean
    disabled?: boolean
    getIndex(id: UniqueIdentifier): number
    renderChildItem(item: Item): JSX.Element | null
    item: Item
}

function SortableItem<Item extends VDNDChildItem>({
    disabled,
    id,
    index,
    handle,
    renderChildItem,
    item,
}: SortableItemProps<Item>): JSX.Element {
    const { setNodeRef, setActivatorNodeRef, listeners, isDragging, isSorting, transform, transition } = useSortable({
        id,
    })
    const mounted = useMountStatus()
    const mountedWhileDragging = isDragging && !mounted

    return (
        <ChildItem
            ref={disabled ? undefined : setNodeRef}
            childItemId={id}
            isDragging={isDragging}
            sorting={isSorting}
            handleProps={handle ? { ref: setActivatorNodeRef } : undefined}
            index={index}
            transition={transition}
            transform={transform}
            fadeIn={mountedWhileDragging}
            listeners={listeners}
            renderChildItem={renderChildItem}
            item={item}
        />
    )
}

function useMountStatus(): boolean {
    const [isMounted, setIsMounted] = useState(false)

    useEffect(() => {
        const timeout = setTimeout(() => setIsMounted(true), 500)

        return () => clearTimeout(timeout)
    }, [])

    return isMounted
}

function DroppableContainer<ChildItem extends VDNDChildItem, ContainerItem extends VNDNDContainerItem<ChildItem>>({
    children,
    columns = 1,
    disabled,
    items,
    style,
    containerItemId,
    ...props
}: ContainerProps<ContainerItem> & {
    disabled?: boolean
    items: ChildItem[]
    style?: React.CSSProperties
}): JSX.Element {
    const { active, attributes, isDragging, listeners, over, setNodeRef, transition, transform } = useSortable({
        id: containerItemId,
        data: {
            type: 'container',
            children: items,
        },
        animateLayoutChanges,
    })
    const isOverContainer = over
        ? (containerItemId === over.id && active?.data.current?.type !== 'container') ||
          items.some((item) => item.id === over.id)
        : false

    return (
        <Container
            ref={disabled ? undefined : setNodeRef}
            isDragging={isDragging}
            hover={isOverContainer}
            transform={CSS.Translate.toString(transform)}
            transition={transition}
            handleProps={{
                ...attributes,
                ...listeners,
            }}
            columns={columns}
            containerItemId={containerItemId}
            {...props}
        >
            {children}
        </Container>
    )
}

export interface ContainerProps<Item extends VNDNDContainerItem<any>> {
    children: React.ReactNode
    columns?: number
    containerItemId: UniqueIdentifier
    style?: React.CSSProperties
    horizontal?: boolean
    hover?: boolean
    handleProps?: React.HTMLAttributes<any>
    scrollable?: boolean
    shadow?: boolean
    placeholder?: boolean
    unstyled?: boolean
    onClick?(): void
    onRemove?(): void
    onAddChild(containerId: UniqueIdentifier): void
    isDragging?: boolean
    transition?: string
    transform?: string
    renderContainerItem(item: Item): JSX.Element | null
    item: Item
}

export const Container = forwardRef(function Container_<Item extends VNDNDContainerItem<any>>(
    {
        children,
        handleProps,
        horizontal,
        hover,
        onClick,
        onRemove,
        onAddChild,
        containerItemId,
        placeholder,
        style,
        scrollable,
        shadow,
        unstyled,
        isDragging,
        transform,
        transition,
        renderContainerItem,
        item,
        ...props
    }: ContainerProps<Item>,
    ref: React.ForwardedRef<HTMLDivElement>
) {
    const Component = onClick ? 'button' : 'div'

    return (
        <Component
            {...props}
            className={`flex flex-col p-4 bg-bg-light border rounded overflow-hidden space-y-2 ${
                isDragging ? 'opacity-40' : ''
            }`}
            style={{
                transform,
                transition,
            }}
            // @ts-expect-error
            ref={ref}
            onClick={onClick}
            tabIndex={onClick ? 0 : undefined}
        >
            <div className="flex flex-row justify-between px-2 space-x-2">
                <Handle {...handleProps} />
                <div>{renderContainerItem ? renderContainerItem(item) : <span>Container {containerItemId}</span>}</div>
                <div className="flex-1" />
                <Remove onClick={onRemove} />
            </div>
            {placeholder ? children : <ul className="space-y-2">{children}</ul>}
            <div className="flex flex-row justify-between px-2 mb-2 space-x-2">
                <LemonButton
                    onClick={onRemove ? () => onAddChild(item.id) : undefined}
                    fullWidth={false}
                    type="secondary"
                >
                    Add child
                </LemonButton>
            </div>
        </Component>
    )
})

export interface ChildItemProps<Item extends VDNDChildItem> {
    dragOverlay?: boolean
    color?: string
    disabled?: boolean
    isDragging?: boolean
    handleProps?: any
    height?: number
    index?: number
    fadeIn?: boolean
    transform?: Transform | null
    listeners?: DraggableSyntheticListeners
    sorting?: boolean
    style?: React.CSSProperties
    transition?: string | null
    wrapperStyle?: React.CSSProperties
    childItemId: UniqueIdentifier
    item: Item
    onRemove?(): void
    renderChildItem(item: Item): JSX.Element | null
}

export const ChildItem = React.memo(
    React.forwardRef<HTMLLIElement, ChildItemProps<any>>(function ChildItem_(
        {
            color,
            dragOverlay,
            isDragging,
            disabled,
            fadeIn,
            handleProps,
            height,
            index,
            listeners,
            onRemove,
            sorting,
            style,
            transition,
            transform,
            childItemId,
            wrapperStyle,
            renderChildItem,
            ...props
        },
        ref
    ) {
        const handle = true
        useEffect(() => {
            if (!dragOverlay) {
                return
            }

            document.body.style.cursor = 'grabbing'

            return () => {
                document.body.style.cursor = ''
            }
        }, [dragOverlay])

        return (
            <li
                ref={ref}
                className={`flex p-[calc(0.5rem-1px)] bg-bg-light border rounded overflow-hidden ${
                    isDragging ? 'opacity-40' : ''
                }`}
            >
                <div
                    data-cypress="draggable-item"
                    {...(!handle ? listeners : undefined)}
                    {...props}
                    tabIndex={!handle ? 0 : undefined}
                    className="flex flex-row justify-between w-full space-x-2"
                >
                    <Handle {...handleProps} {...listeners} />
                    <div>{renderChildItem ? renderChildItem(childItemId) : <span>Item {childItemId}</span>}</div>
                    <div className="flex-1" />
                    <Remove onClick={onRemove} />
                </div>
            </li>
        )
    })
)

export function Remove(props: LemonButtonProps): JSX.Element {
    return (
        <LemonButton type="secondary" fullWidth={false} status="danger" {...props}>
            <IconTrash />
        </LemonButton>
    )
}

export const Handle = forwardRef<HTMLButtonElement, LemonButtonProps>(function Handle_(props, ref) {
    return (
        <LemonButton type="secondary" fullWidth={false} ref={ref} {...props}>
            <IconBuilding />
        </LemonButton>
    )
})
