import { DndContext } from '@dnd-kit/core'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'
import { forwardRef, HTMLAttributes, useCallback, useEffect, useRef, useState } from 'react'

import { LemonButton, SideAction } from '../LemonButton'
import { LemonSkeleton } from '../LemonSkeleton'
import { getIcon, TreeNodeDraggable, TreeNodeDroppable } from './utils'

export type TreeDataItem = {
    /** The ID of the item. */
    id: string
    /** The name of the item. */
    name: string
    /** Passthrough metadata */
    record?: Record<string, any>
    /** The icon to use for the item. */
    icon?: React.ReactNode
    /** The children of the item. */
    children?: TreeDataItem[]
    /** Disabled: The reason the item is disabled. */
    disabledReason?: string
    /**
     * Handle a click on the item.
     * @param open - boolean to indicate if it's a folder and it's open state
     */
    onClick?: (open?: boolean) => void

    /** The type of the item. */
    type: 'folder' | 'file' | 'project' | 'separator' | 'loading'

    /** The path of the item. */
    filePath?: string
}

type LemonTreeBaseProps = Omit<HTMLAttributes<HTMLDivElement>, 'onDragEnd'> & {
    /** The data to render in the tree. */
    data: TreeDataItem[] | TreeDataItem
    /** The ID of the folder/node to select by default. Will expand the node if it has children. */
    defaultSelectedFolderOrNodeId?: string
    /** The IDs of the expanded items. */
    expandedItemIds: string[]
    /** The icon to use for node items. Defaults to <IconChevronRight />. */
    defaultNodeIcon?: React.ReactNode
    /** Whether to show an active state on folder nodes when selected. Defaults to false. */
    showFolderActiveState?: boolean
    /** Whether the item is draggable */
    isItemDraggable?: (item: TreeDataItem) => boolean
    /** Whether the item can accept drops */
    isItemDroppable?: (item: TreeDataItem) => boolean
    /** The side action to render for the item. */
    itemSideAction?: (item: TreeDataItem) => SideAction
    /** Whether the item is loading */
    isItemLoading?: (item: TreeDataItem) => boolean
    /** Whether the item is unapplied */
    isItemUnapplied?: (item: TreeDataItem) => boolean
    /** The render function for the item. */
    renderItem?: (item: TreeDataItem, children: React.ReactNode) => React.ReactNode
    /** Set the IDs of the expanded items. */
    onSetExpandedItemIds?: (ids: string[]) => void
}

export type LemonTreeProps = LemonTreeBaseProps & {
    /** Whether to expand all folders by default. Defaults to false. Disabled folders will not be expanded. */
    expandAllFolders?: boolean
    /** handler for folder clicks.*/
    onFolderClick?: (folder: TreeDataItem | undefined, isExpanded: boolean) => void
    /** handler for node clicks. */
    onNodeClick?: (node: TreeDataItem | undefined) => void
    /** The ref of the content to focus when the tree is clicked. TODO: make non-optional. */
    contentRef?: React.RefObject<HTMLElement>
    /** Handler for when a drag operation completes */
    onDragEnd?: (sourceId: string, targetId: string) => void
}

export type LemonTreeNodeProps = LemonTreeBaseProps & {
    /** The ID of the item. */
    selectedId?: string
    /** The ID of the focused item. */
    focusedId?: string
    /** Handle a click on the item. */
    handleClick: (item: TreeDataItem | undefined) => void
    /** Whether the item is draggable. */
    isDraggable?: (item: TreeDataItem) => boolean
    /** Whether the item is droppable. */
    isDroppable?: (item: TreeDataItem) => boolean
    /** The depth of the item. */
    depth?: number
}

const LemonTreeNode = forwardRef<HTMLDivElement, LemonTreeNodeProps>(
    (
        {
            className,
            data,
            selectedId,
            focusedId,
            handleClick,
            renderItem,
            expandedItemIds,
            onSetExpandedItemIds,
            defaultNodeIcon,
            showFolderActiveState,
            isItemDraggable: isDraggable,
            isItemDroppable: isDroppable,
            depth = 0,
            itemSideAction,
        },
        ref
    ): JSX.Element => {
        const DEPTH_OFFSET = 4 + 8 * depth // 4 is .25rem to match lemon button padding x axis

        // Handle meta key to enable dragging
        const [isModifierKeyPressed, setIsModifierKeyPressed] = useState(false)

        if (!(data instanceof Array)) {
            data = [data]
        }

        // TODO: move this kea
        useEffect(() => {
            const handleKeyDown = (e: KeyboardEvent): void => {
                if (e.metaKey || e.ctrlKey) {
                    setIsModifierKeyPressed(true)
                }
            }

            const handleKeyUp = (e: KeyboardEvent): void => {
                if (!e.metaKey && !e.ctrlKey) {
                    setIsModifierKeyPressed(false)
                }
            }

            window.addEventListener('keydown', handleKeyDown)
            window.addEventListener('keyup', handleKeyUp)

            return () => {
                window.removeEventListener('keydown', handleKeyDown)
                window.removeEventListener('keyup', handleKeyUp)
            }
        }, [])

        return (
            <ul className={cn('list-none m-0 p-0', className)} role="group">
                {data.map((item) => {
                    const content = (
                        <AccordionPrimitive.Root
                            type="multiple"
                            value={expandedItemIds}
                            onValueChange={(s) => onSetExpandedItemIds?.(s)}
                            ref={ref}
                            key={item.id}
                            disabled={!!item.disabledReason}
                        >
                            <AccordionPrimitive.Item value={item.id} className="flex flex-col w-full">
                                <AccordionPrimitive.Trigger className="flex items-center gap-2 w-full h-8" asChild>
                                    <LemonButton
                                        className={cn(
                                            'flex-1 flex items-center gap-2 cursor-pointer font-normal',
                                            focusedId === item.id &&
                                                'ring-2 ring-inset ring-offset-[-1px] ring-accent-primary'
                                        )}
                                        onClick={() => handleClick(item)}
                                        type="tertiary"
                                        role="treeitem"
                                        tabIndex={-1}
                                        size="small"
                                        fullWidth
                                        data-id={item.id}
                                        data-tree-depth={depth}
                                        active={
                                            selectedId === item.id ||
                                            (showFolderActiveState &&
                                                item.children &&
                                                expandedItemIds.includes(item.id))
                                        }
                                        icon={getIcon({ item, expandedItemIds, defaultNodeIcon })}
                                        disabledReason={item.disabledReason}
                                        tooltipPlacement="right"
                                        style={{ paddingLeft: `${DEPTH_OFFSET}px` }}
                                        truncate
                                        tooltip={item.name}
                                        sideAction={itemSideAction ? itemSideAction(item) : undefined}
                                    >
                                        <span
                                            className={cn('', {
                                                'font-bold': selectedId === item.id,
                                                'text-secondary': item.disabledReason,
                                            })}
                                        >
                                            {renderItem ? renderItem(item, item.name) : item.name}
                                        </span>
                                    </LemonButton>
                                </AccordionPrimitive.Trigger>

                                {item.children && (
                                    <AccordionPrimitive.Content className="relative">
                                        {/* Depth line */}
                                        <div
                                            className="absolute -top-2 left-0 bottom-0 w-px -z-[1] bg-fill-separator"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ transform: `translateX(${DEPTH_OFFSET}px)` }}
                                        />
                                        <LemonTreeNode
                                            data={item.children}
                                            selectedId={selectedId}
                                            focusedId={focusedId}
                                            handleClick={handleClick}
                                            expandedItemIds={expandedItemIds}
                                            onSetExpandedItemIds={onSetExpandedItemIds}
                                            defaultNodeIcon={defaultNodeIcon}
                                            showFolderActiveState={showFolderActiveState}
                                            renderItem={renderItem}
                                            itemSideAction={itemSideAction}
                                            className="space-y-px"
                                            isItemDraggable={isDraggable}
                                            isItemDroppable={isDroppable}
                                            depth={depth + 1}
                                        />
                                    </AccordionPrimitive.Content>
                                )}
                            </AccordionPrimitive.Item>
                        </AccordionPrimitive.Root>
                    )

                    if (item.type === 'loading') {
                        return <LemonSkeleton key={item.id} className="h-[33px] w-full" />
                    }

                    // Wrap content in Draggable/Droppable if needed
                    let wrappedContent = content
                    if (isDraggable?.(item) && item.filePath) {
                        wrappedContent = (
                            <TreeNodeDraggable id={item.filePath} enableDragging={isModifierKeyPressed}>
                                {wrappedContent}
                            </TreeNodeDraggable>
                        )
                    }
                    if (isDroppable?.(item) && item.filePath) {
                        wrappedContent = (
                            <TreeNodeDroppable id={item.filePath} isDroppable={isDroppable(item)}>
                                {wrappedContent}
                            </TreeNodeDroppable>
                        )
                    }

                    return <div key={item.id}>{wrappedContent}</div>
                })}
            </ul>
        )
    }
)
LemonTreeNode.displayName = 'LemonTreeNode'

const LemonTree = forwardRef<HTMLDivElement, LemonTreeProps>(
    (
        {
            data,
            defaultSelectedFolderOrNodeId,
            onFolderClick,
            onNodeClick,
            expandAllFolders = false,
            defaultNodeIcon,
            className,
            showFolderActiveState = false,
            contentRef,
            onDragEnd,
            isItemDraggable: isDraggable,
            isItemDroppable: isDroppable,
            isItemLoading,
            isItemUnapplied,
            itemSideAction,
            expandedItemIds,
            onSetExpandedItemIds,
            ...props
        },
        ref
    ): JSX.Element => {
        const TYPE_AHEAD_TIMEOUT = 500
        // Scrollable container
        const containerRef = useRef<HTMLDivElement>(null)

        // Selected item (you click on it)
        const [selectedId, setSelectedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        // Focused item (you press arrow keys to navigate)
        const [focusedId, setFocusedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        // Type-ahead buffer (you type while in focus of the tree)
        const [typeAheadBuffer, setTypeAheadBuffer] = useState<string>('')
        const typeAheadTimeoutRef = useRef<NodeJS.Timeout>()

        function collectAllFolderIds(items: TreeDataItem[] | TreeDataItem, allIds: string[]): void {
            if (items instanceof Array) {
                items.forEach((item) => {
                    if (!item.disabledReason && item.type === 'folder') {
                        allIds.push(item.id)
                    }
                    if (item.children) {
                        collectAllFolderIds(item.children, allIds)
                    }
                })
            } else {
                if (!items.disabledReason && items.type === 'folder') {
                    allIds.push(items.id)
                }
                if (items.children) {
                    collectAllFolderIds(items.children, allIds)
                }
            }
        }

        const [expandedItemIdsState, setExpandedItemIdsState] = useState<string[]>((): string[] => {
            // Start with expandedItemIds prop or empty array
            const ids: string[] = [...(expandedItemIds ?? [])]

            if (expandAllFolders) {
                // If expandAll is true, collect all item IDs
                const allIds: string[] = []
                collectAllFolderIds(data, allIds)
                ids.push(...allIds)
            }

            function walkTreeItems(items: TreeDataItem[] | TreeDataItem, targetId: string): boolean {
                if (items instanceof Array) {
                    for (const item of items) {
                        ids.push(item.id)
                        if (walkTreeItems(item, targetId)) {
                            return true
                        }
                        ids.pop()
                    }
                } else if (items.id === targetId) {
                    return true
                } else if (items.children) {
                    return walkTreeItems(items.children, targetId)
                }
                return false
            }

            // If not expandAll, only expand path to selected item
            if (defaultSelectedFolderOrNodeId) {
                walkTreeItems(data, defaultSelectedFolderOrNodeId)
            }

            // Remove duplicates and update parent state if callback provided
            const uniqueIds = [...new Set(ids)]
            onSetExpandedItemIds && onSetExpandedItemIds(uniqueIds)
            return uniqueIds
        })

        // Flatten visible tree items for keyboard navigation
        const getVisibleItems = useCallback((): TreeDataItem[] => {
            const items: TreeDataItem[] = []

            const traverse = (nodes: TreeDataItem[] | TreeDataItem): void => {
                const nodeArray = nodes instanceof Array ? nodes : [nodes]

                nodeArray.forEach((node) => {
                    items.push(node)
                    if (node.children && expandedItemIdsState.includes(node.id)) {
                        traverse(node.children)
                    }
                })
            }

            traverse(data)
            return items
        }, [data, expandedItemIdsState])

        // Focus on provided content ref
        const focusContent = useCallback(() => {
            if (contentRef?.current) {
                contentRef.current.focus()
                setFocusedId(undefined) // Remove focus from tree when moving to content
            }
        }, [contentRef])

        // Add helper function to find path to an item
        const findPathToItem = useCallback((items: TreeDataItem[], targetId: string, path: string[] = []): string[] => {
            for (const item of items) {
                if (item.id === targetId) {
                    return path
                }
                if (item.children) {
                    const newPath = findPathToItem(item.children, targetId, [...path, item.id])
                    if (newPath.length > 0) {
                        return newPath
                    }
                }
            }
            return []
        }, [])

        // Add function to handle type-ahead search
        const handleTypeAhead = useCallback(
            (char: string) => {
                // Clear existing timeout
                if (typeAheadTimeoutRef.current) {
                    clearTimeout(typeAheadTimeoutRef.current)
                }

                // Update buffer with new character
                const newBuffer = typeAheadBuffer + char.toLowerCase()
                setTypeAheadBuffer(newBuffer)

                // Set timeout to clear buffer after 1.5 seconds
                typeAheadTimeoutRef.current = setTimeout(() => {
                    setTypeAheadBuffer('')
                }, TYPE_AHEAD_TIMEOUT)

                // Find matching item
                const visibleItems = getVisibleItems()
                const currentIndex = visibleItems.findIndex((item) => item.id === focusedId)

                // Start search from item after current focus, wrapping to start if needed
                const searchItems = [
                    ...visibleItems.slice(currentIndex + 1),
                    ...visibleItems.slice(0, currentIndex + 1),
                ]

                const match = searchItems.find((item) => item.name.toLowerCase().startsWith(newBuffer))

                if (match) {
                    setFocusedId(match.id)
                    // If item is in a collapsed folder, expand the path to it
                    const path = findPathToItem(Array.isArray(data) ? data : [data], match.id)
                    if (path.length > 0) {
                        setExpandedItemIdsState([...new Set([...expandedItemIdsState, ...path])])
                        onSetExpandedItemIds && onSetExpandedItemIds([...new Set([...expandedItemIdsState, ...path])])
                    }
                }
            },
            [
                typeAheadBuffer,
                focusedId,
                getVisibleItems,
                data,
                expandedItemIds,
                findPathToItem,
                onSetExpandedItemIds,
                expandedItemIdsState,
            ]
        )

        const handleClick = useCallback(
            (item: TreeDataItem | undefined, isKeyboardAction = false): void => {
                // Update focusedId when clicking
                setFocusedId(item?.id)

                // Handle click on a node
                if (item?.type === 'file') {
                    if (onNodeClick) {
                        setSelectedId(item?.id)
                        onNodeClick(item)
                        // Only focus content if this was triggered by a keyboard action
                        if (isKeyboardAction) {
                            // Focus content when keyboard action on a node
                            focusContent()
                            //Hide focus when keyboard action on a node
                            setFocusedId(undefined)
                        }
                    }
                } else if (item?.type === 'folder') {
                    // Handle click on a folder
                    if (onFolderClick) {
                        onFolderClick(item, !expandedItemIdsState.includes(item.id))
                    }
                }
                if (item?.onClick) {
                    // Handle custom click handler for a folder/ node, pass true if it's a folder and it's not open (yet)
                    const willBeOpen = item?.children ? !expandedItemIdsState.includes(item.id) : undefined
                    item.onClick(willBeOpen)
                }
            },
            [expandedItemIdsState, onFolderClick, onNodeClick, focusContent]
        )

        // Update handleKeyDown to include type-ahead
        const handleKeyDown = useCallback(
            (e: React.KeyboardEvent) => {
                // Handle single printable characters for type-ahead
                if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
                    handleTypeAhead(e.key)
                    return
                }

                const visibleItems = getVisibleItems()
                const currentIndex = visibleItems.findIndex((item) => item.id === focusedId)

                // Handle keyboard navigation
                // Following https://www.w3.org/WAI/ARIA/apg/patterns/treeview/
                switch (e.key) {
                    // Right arrow:
                    // When focus is on a closed node, opens the node; focus does not move.
                    // When focus is on a open node, moves focus to the first child node.
                    // When focus is on an end node, does nothing.
                    case 'ArrowRight': {
                        e.preventDefault()
                        const currentItem = visibleItems[currentIndex]
                        // Expand folder if current item is an unexpanded, non-disabled folder
                        if (currentItem?.children && !currentItem.disabledReason) {
                            // If folder is not expanded, expand it
                            if (!expandedItemIdsState.includes(currentItem.id)) {
                                setExpandedItemIdsState([...expandedItemIdsState, currentItem.id])
                                onSetExpandedItemIds && onSetExpandedItemIds([...expandedItemIdsState, currentItem.id])
                            } else {
                                // If folder is already expanded, focus first child
                                const nextItem = visibleItems[currentIndex + 1]
                                if (nextItem) {
                                    setFocusedId(nextItem.id)
                                    // setSelectedId(undefined)
                                }
                            }
                        }
                        break
                    }

                    // Left arrow:
                    // When focus is on an open node, closes the node.
                    // When focus is on a child node that is also either an end node or a closed node, moves focus to its parent node.
                    // When focus is on a root node that is also either an end node or a closed node, does nothing.
                    case 'ArrowLeft': {
                        e.preventDefault()
                        const currentItem = visibleItems[currentIndex]

                        // If current item is an expanded folder, collapse it
                        if (currentItem?.children && expandedItemIdsState.includes(currentItem.id)) {
                            setExpandedItemIdsState(expandedItemIdsState.filter((id) => id !== currentItem.id))
                            onSetExpandedItemIds &&
                                onSetExpandedItemIds(expandedItemIdsState.filter((id) => id !== currentItem.id))
                            return
                        }

                        // Find parent of current item
                        const findParent = (items: TreeDataItem[], targetId: string): TreeDataItem | null => {
                            for (const item of items) {
                                if (item.children?.some((child) => child.id === targetId)) {
                                    return item
                                }
                                if (item.children) {
                                    const found = findParent(item.children, targetId)
                                    if (found) {
                                        return found
                                    }
                                }
                            }
                            return null
                        }

                        // Find parent folder
                        const parentItem = findParent(Array.isArray(data) ? data : [data], currentItem.id)
                        if (parentItem) {
                            // If parent is expanded, collapse it and focus it
                            if (expandedItemIdsState.includes(parentItem.id)) {
                                setExpandedItemIdsState(expandedItemIdsState.filter((id) => id !== parentItem.id))
                                onSetExpandedItemIds &&
                                    onSetExpandedItemIds(expandedItemIdsState.filter((id) => id !== parentItem.id))
                                setFocusedId(parentItem.id)
                            } else {
                                // If parent is already collapsed, just focus it
                                setFocusedId(parentItem.id)
                            }
                        }
                        break
                    }

                    // Down Arrow:
                    // Moves focus to the next node that is focusable without opening or closing a node.
                    case 'ArrowDown': {
                        e.preventDefault()
                        if (currentIndex === -1) {
                            // If no item is focused, focus the first item
                            if (visibleItems.length > 0) {
                                setFocusedId(visibleItems[0].id)
                                setSelectedId(undefined)
                            }
                        } else if (currentIndex < visibleItems.length - 1) {
                            setFocusedId(visibleItems[currentIndex + 1].id)
                            // setSelectedId(undefined)
                        }
                        break
                    }

                    // Up Arrow:
                    // Moves focus to the previous node that is focusable without opening or closing a node.
                    case 'ArrowUp': {
                        e.preventDefault()
                        if (currentIndex === -1) {
                            // If no item is focused, focus the first item
                            if (visibleItems.length > 0) {
                                setFocusedId(visibleItems[0].id)
                                setSelectedId(undefined)
                            }
                        } else if (currentIndex > 0) {
                            // Otherwise move focus to previous item
                            setFocusedId(visibleItems[currentIndex - 1].id)
                            // setSelectedId(undefined)
                        }
                        break
                    }

                    // Home:
                    // Moves focus to the first node in the tree that is focusable without opening a node.
                    case 'Home': {
                        e.preventDefault()
                        const visibleItems = getVisibleItems()
                        if (visibleItems.length > 0) {
                            setFocusedId(visibleItems[0].id)
                        }
                        break
                    }

                    // End:
                    // Moves focus to the last node in the tree that is focusable without opening a node.
                    case 'End': {
                        e.preventDefault()
                        const visibleItems = getVisibleItems()
                        if (visibleItems.length > 0) {
                            setFocusedId(visibleItems[visibleItems.length - 1].id)
                        }
                        break
                    }

                    // Enter:
                    // Activates the current item.
                    case 'Enter': {
                        e.preventDefault()
                        const currentItem = visibleItems[currentIndex]

                        // Skip if item is disabled
                        if (!currentItem.disabledReason) {
                            if (currentItem.children) {
                                // Handle folder click
                                handleClick(currentItem, true)

                                // Toggle folder expanded state
                                if (expandedItemIdsState.includes(currentItem.id)) {
                                    // Close folder by removing from expanded IDs
                                    setExpandedItemIdsState(expandedItemIdsState.filter((id) => id !== currentItem.id))
                                    onSetExpandedItemIds &&
                                        onSetExpandedItemIds(expandedItemIdsState.filter((id) => id !== currentItem.id))
                                } else {
                                    // Open folder by adding to expanded IDs
                                    setExpandedItemIdsState([...expandedItemIdsState, currentItem.id])
                                    onSetExpandedItemIds &&
                                        onSetExpandedItemIds([...expandedItemIdsState, currentItem.id])
                                }
                            } else {
                                if (onNodeClick) {
                                    // Otherwise use default node click handler
                                    onNodeClick(currentItem)

                                    // Set selectedId to currentItem.id
                                    setSelectedId(currentItem.id)

                                    if (currentItem.onClick) {
                                        // Use item's custom click handler if provided
                                        currentItem.onClick()
                                    }

                                    focusContent()
                                }
                            }
                        }
                        break
                    }
                }
            },
            [
                focusedId,
                expandedItemIdsState,
                getVisibleItems,
                handleTypeAhead,
                data,
                focusContent,
                handleClick,
                onNodeClick,
                onSetExpandedItemIds,
            ]
        )

        // Add function to scroll focused item into view
        const scrollFocusedIntoView = useCallback(() => {
            if (!containerRef.current) {
                return
            }

            // Look for either focused or selected element
            const elementId = focusedId || selectedId
            if (!elementId) {
                return
            }

            // Find the element
            const element = containerRef.current.querySelector(`[data-id="${elementId}"]`)
            if (!element) {
                return
            }

            // Get container bounds
            const containerBounds = containerRef.current.getBoundingClientRect()
            const elementBounds = element.getBoundingClientRect()

            // Calculate if element is outside visible area
            const SCROLL_PADDING = 32 // Smaller padding at bottom of container
            const isAbove = elementBounds.top < containerBounds.top
            const isBelow = elementBounds.bottom > containerBounds.bottom - SCROLL_PADDING

            if (isAbove || isBelow) {
                element.scrollIntoView({
                    block: isBelow ? 'end' : 'start',
                    behavior: 'smooth',
                })
            }
        }, [selectedId, focusedId])

        // TODO: Add effect to scroll when focusedId changes
        useEffect(() => {
            scrollFocusedIntoView()
        }, [selectedId, focusedId, scrollFocusedIntoView])

        useEffect(() => {
            if (defaultSelectedFolderOrNodeId) {
                setFocusedId(defaultSelectedFolderOrNodeId)
                setSelectedId(defaultSelectedFolderOrNodeId)
            }
        }, [defaultSelectedFolderOrNodeId])

        return (
            <DndContext
                onDragEnd={(event) => {
                    if (event.over && event.active.id !== event.over.id && onDragEnd) {
                        onDragEnd(event.active.id as string, event.over.id as string)
                    }
                }}
            >
                <ScrollableShadows
                    direction="vertical"
                    ref={containerRef}
                    tabIndex={0}
                    role="tree"
                    aria-label="Tree navigation"
                    aria-activedescendant={focusedId}
                    onKeyDown={handleKeyDown}
                    onBlur={() => {
                        // Hide focus when blurring the tree
                        setFocusedId(undefined)
                    }}
                    className="flex-1"
                    innerClassName="p-2"
                >
                    <LemonTreeNode
                        data={data}
                        ref={ref}
                        selectedId={selectedId}
                        focusedId={focusedId}
                        handleClick={handleClick}
                        expandedItemIds={expandedItemIdsState}
                        onSetExpandedItemIds={(ids) => {
                            // Set local state
                            setExpandedItemIdsState(ids)
                            // Call prop callback if provided
                            onSetExpandedItemIds?.(ids)
                        }}
                        defaultNodeIcon={defaultNodeIcon}
                        showFolderActiveState={showFolderActiveState}
                        className="space-y-px"
                        isItemDraggable={isDraggable}
                        isItemDroppable={isDroppable}
                        isItemLoading={isItemLoading}
                        isItemUnapplied={isItemUnapplied}
                        itemSideAction={itemSideAction}
                        {...props}
                    />
                </ScrollableShadows>
            </DndContext>
        )
    }
)
LemonTree.displayName = 'LemonTree'

export { LemonTree }
