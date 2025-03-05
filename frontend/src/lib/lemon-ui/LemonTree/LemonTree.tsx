import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { IconUpload } from '@posthog/icons'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'
import { forwardRef, HTMLAttributes, useCallback, useEffect, useRef, useState } from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '../../ui/ContextMenu/ContextMenu'
import { LemonButton, SideAction } from '../LemonButton'
import { Spinner } from '../Spinner/Spinner'
import { getIcon, TreeNodeDraggable, TreeNodeDroppable } from './LemonTreeUtils'

export type TreeDataItem = {
    /** The ID of the item. */
    id: string
    /** The name of the item. */
    name: string
    /** Passthrough metadata */
    record?: Record<string, any>
    /** The side action to render for the item. */
    itemSideAction?: (item: TreeDataItem) => SideAction
    /** The icon to use for the item. */
    icon?: React.ReactNode
    /** The children of the item. */
    children?: TreeDataItem[]
    /** Disabled: The reason the item is disabled. */
    disabledReason?: string

    type?: 'node' | 'separator'
    /**
     * Handle a click on the item.
     * @param open - boolean to indicate if it's a folder and it's open state
     */
    onClick?: (open?: boolean) => void
}

type LemonTreeBaseProps = Omit<HTMLAttributes<HTMLDivElement>, 'onDragEnd'> & {
    /** The data to render in the tree. */
    data: TreeDataItem[] | TreeDataItem
    /** The ID of the folder/node to select by default. Will expand the node if it has children. */
    defaultSelectedFolderOrNodeId?: string
    /** The IDs of the expanded items. */
    expandedItemIds?: string[]
    /** The icon to use for node items. Defaults to <IconChevronRight />. */
    defaultNodeIcon?: React.ReactNode
    /** Whether to show an active state on folder nodes when selected. Defaults to false. */
    showFolderActiveState?: boolean
    /** Whether to enable drag and drop of items. */
    enableDragAndDrop?: boolean
    /** Whether the item is draggable */
    isItemDraggable?: (item: TreeDataItem) => boolean
    /** Whether the item can accept drops */
    isItemDroppable?: (item: TreeDataItem) => boolean
    /** The side action to render for the item. */
    itemSideAction?: (item: TreeDataItem) => SideAction | undefined
    /** The context menu to render for the item. */
    itemContextMenu?: (item: TreeDataItem) => React.ReactNode
    /** Whether the item is loading */
    isItemLoading?: (item: TreeDataItem) => boolean
    /** Whether the item is unapplied */
    isItemUnapplied?: (item: TreeDataItem) => boolean
    /** The render function for the item. */
    renderItem?: (item: TreeDataItem, children: React.ReactNode) => React.ReactNode
    /** Set the IDs of the expanded items. */
    onSetExpandedItemIds?: (ids: string[]) => void
    /** Pass true if you need to wait for async events to populate the tree. If present and true will trigger: scrolling to focused item */
    isFinishedBuildingTreeData?: boolean
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
    onDragEnd?: (dragEvent: DragEndEvent) => void
}

export type LemonTreeNodeProps = LemonTreeBaseProps & {
    /** The ID of the item. */
    selectedId?: string
    /** The ID of the focused item. */
    focusedId?: string
    /** Handle a click on the item. */
    handleClick: (item: TreeDataItem | undefined, isKeyboardAction?: boolean) => void
    /** The depth of the item. */
    depth?: number
    /** Whether the context menu is open */
    onContextMenuOpen?: (open: boolean) => void
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
            isItemDraggable,
            isItemDroppable,
            depth = 0,
            itemSideAction,
            enableDragAndDrop = false,
            onContextMenuOpen,
            itemContextMenu,
            ...props
        },
        ref
    ): JSX.Element => {
        const DEPTH_OFFSET = 4 + 8 * depth // 4 is .25rem to match lemon button padding x axis

        const [isContextMenuOpenForItem, setIsContextMenuOpenForItem] = useState<string | undefined>(undefined)

        if (!(data instanceof Array)) {
            data = [data]
        }

        function handleContextMenuOpen(open: boolean, itemId: string): void {
            // Set local state
            setIsContextMenuOpenForItem(open ? itemId : undefined)

            // Tell parent that the context menu is open
            onContextMenuOpen?.(open)
        }

        return (
            <ul className={cn('list-none m-0 p-0', className)} role="group">
                {data.map((item) => {
                    // Clean up display name by replacing escaped characters
                    const displayName = item.name.replace(/\\\//g, '/').replace(/\\/g, '')

                    if (item.type === 'separator') {
                        return (
                            <div key={item.id} className="h-1 -mx-2 flex items-center">
                                <div className="border-b border-primary h-px my-2 flex-1" />
                            </div>
                        )
                    }

                    let cursorClass = 'cursor-pointer'

                    if (enableDragAndDrop) {
                        if (isItemDraggable?.(item)) {
                            cursorClass = 'cursor-grab'
                        } else {
                            cursorClass = 'cursor-not-allowed'
                        }
                    } else {
                        cursorClass = 'cursor-pointer'
                    }

                    const content = (
                        <AccordionPrimitive.Root
                            type="multiple"
                            value={expandedItemIds}
                            onValueChange={(s) => {
                                onSetExpandedItemIds?.(s)
                            }}
                            ref={ref}
                            key={item.id}
                            disabled={!!item.disabledReason}
                        >
                            <AccordionPrimitive.Item value={item.id} className="flex flex-col w-full">
                                <AccordionPrimitive.Trigger className="flex items-center gap-2 w-full h-8" asChild>
                                    <ContextMenu
                                        onOpenChange={(open) => {
                                            handleContextMenuOpen(open, item.id)
                                        }}
                                    >
                                        <ContextMenuTrigger asChild>
                                            <LemonButton
                                                className={cn(
                                                    'group/lemon-tree-button',
                                                    'flex-1 flex items-center gap-2 font-normal',
                                                    cursorClass,
                                                    (focusedId === item.id || isContextMenuOpenForItem === item.id) &&
                                                        'ring-2 ring-inset ring-offset-[-1px] ring-accent-primary',
                                                    selectedId === item.id &&
                                                        'border-l-[4px] border-l-accent-primary rounded-tl-sm rounded-bl-sm'
                                                )}
                                                onClick={() => {
                                                    if (!enableDragAndDrop) {
                                                        handleClick(item)
                                                    }
                                                }}
                                                onKeyDown={(e) => e.key === 'Enter' && handleClick(item, true)}
                                                type="tertiary"
                                                role="treeitem"
                                                tabIndex={-1}
                                                size="small"
                                                fullWidth
                                                data-id={item.id}
                                                active={
                                                    selectedId === item.id ||
                                                    (showFolderActiveState &&
                                                        item.children &&
                                                        expandedItemIds?.includes(item.id))
                                                }
                                                icon={getIcon({
                                                    item,
                                                    expandedItemIds: expandedItemIds ?? [],
                                                    defaultNodeIcon,
                                                })}
                                                disabled={!isItemDraggable?.(item) && enableDragAndDrop}
                                                tooltip={displayName}
                                                tooltipPlacement="right"
                                                style={{ paddingLeft: `${DEPTH_OFFSET}px` }}
                                                truncate
                                                sideAction={itemSideAction ? itemSideAction(item) : undefined}
                                            >
                                                <span
                                                    className={cn('', {
                                                        'font-bold': selectedId === item.id,
                                                        'text-secondary': item.disabledReason,
                                                    })}
                                                >
                                                    {renderItem ? (
                                                        <>
                                                            {renderItem(item, displayName)}
                                                            {item.record?.loading && <Spinner className="ml-1" />}
                                                            {item.record?.unapplied && (
                                                                <IconUpload className="ml-1 text-warning" />
                                                            )}
                                                        </>
                                                    ) : (
                                                        displayName
                                                    )}
                                                </span>
                                            </LemonButton>
                                        </ContextMenuTrigger>

                                        {isContextMenuOpenForItem === item.id && itemContextMenu?.(item) ? (
                                            <ContextMenuContent loop>{itemContextMenu(item)}</ContextMenuContent>
                                        ) : null}
                                    </ContextMenu>
                                </AccordionPrimitive.Trigger>

                                {item.children && (
                                    <AccordionPrimitive.Content className="relative">
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
                                            className="deprecated-space-y-px"
                                            depth={depth + 1}
                                            isItemDraggable={isItemDraggable}
                                            isItemDroppable={isItemDroppable}
                                            enableDragAndDrop={enableDragAndDrop}
                                            onContextMenuOpen={onContextMenuOpen}
                                            itemContextMenu={itemContextMenu}
                                            {...props}
                                        />
                                    </AccordionPrimitive.Content>
                                )}
                            </AccordionPrimitive.Item>
                        </AccordionPrimitive.Root>
                    )

                    // Wrap content in Draggable/Droppable if needed
                    let wrappedContent = content
                    const path = item.record?.path || ''

                    if (isItemDraggable?.(item)) {
                        wrappedContent = (
                            <TreeNodeDroppable id={path} isDroppable={isItemDroppable?.(item) && path}>
                                <TreeNodeDraggable
                                    id={path}
                                    enableDragging={isItemDraggable(item) && enableDragAndDrop}
                                >
                                    {wrappedContent}
                                </TreeNodeDraggable>
                            </TreeNodeDroppable>
                        )
                    } else if (isItemDroppable?.(item)) {
                        wrappedContent = (
                            <TreeNodeDroppable id={path} isDroppable={isItemDroppable(item)}>
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
            expandedItemIds,
            onSetExpandedItemIds,
            isItemDraggable,
            isItemDroppable,
            itemSideAction,
            enableDragAndDrop = false,
            itemContextMenu,
            isFinishedBuildingTreeData,
            ...props
        },
        ref
    ): JSX.Element => {
        const TYPE_AHEAD_TIMEOUT = 500
        // Scrollable container
        const containerRef = useRef<HTMLDivElement>(null)

        const [selectedId, setSelectedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        const [focusedId, setFocusedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        const [hasFocusedContent, setHasFocusedContent] = useState(false)
        // Add new state for type-ahead
        const [typeAheadBuffer, setTypeAheadBuffer] = useState<string>('')
        const typeAheadTimeoutRef = useRef<NodeJS.Timeout>()
        const [isNodeTreeContextMenuOpen, setIsNodeTreeContextMenuOpen] = useState(false)

        function collectAllFolderIds(items: TreeDataItem[] | TreeDataItem, allIds: string[]): void {
            if (items instanceof Array) {
                items.forEach((item) => {
                    if (!item.disabledReason && item.children) {
                        allIds.push(item.id)
                    }
                    if (item.children) {
                        collectAllFolderIds(item.children, allIds)
                    }
                })
            } else {
                if (!items.disabledReason && items.children) {
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
                    if (node.children && expandedItemIdsState?.includes(node.id)) {
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
                setHasFocusedContent(true)
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
                // Don't allow typeahead when context menu is open
                if (isNodeTreeContextMenuOpen) {
                    return
                }

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
                        const newExpandedIds = [...new Set([...expandedItemIdsState, ...path])]
                        setExpandedItemIdsState(newExpandedIds)
                        onSetExpandedItemIds && onSetExpandedItemIds(newExpandedIds)
                    }
                }
            },
            [
                typeAheadBuffer,
                focusedId,
                getVisibleItems,
                data,
                findPathToItem,
                onSetExpandedItemIds,
                expandedItemIdsState,
                isNodeTreeContextMenuOpen,
            ]
        )

        const handleClick = useCallback(
            (item: TreeDataItem | undefined, isKeyboardAction = false): void => {
                // Update focusedId when clicking
                setFocusedId(item?.id)

                const isFolder = item?.children && item?.children?.length >= 0

                // Handle click on a node
                if (!isFolder) {
                    if (onNodeClick) {
                        setSelectedId(item?.id)
                        onNodeClick(item)
                        // Only focus content if this was triggered by a keyboard action
                        if (isKeyboardAction) {
                            // Focus content when keyboard action on a node
                            focusContent()
                        }
                    }
                } else if (isFolder) {
                    // Handle click on a folder
                    if (onFolderClick) {
                        // Update expanded state
                        const newExpandedIds = expandedItemIdsState.includes(item.id)
                            ? expandedItemIdsState.filter((id) => id !== item.id)
                            : [...expandedItemIdsState, item.id]
                        setExpandedItemIdsState(newExpandedIds)
                        onFolderClick(item, expandedItemIdsState.includes(item.id))
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
                // Don't allow keyboard navigation when context menu is open
                if (isNodeTreeContextMenuOpen) {
                    return
                }

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
                        if (
                            currentItem?.children &&
                            currentItem?.children?.length >= 0 &&
                            !currentItem.disabledReason
                        ) {
                            // If folder is not expanded, expand it
                            if (!expandedItemIdsState.includes(currentItem.id)) {
                                const newExpandedIds = [...new Set([...expandedItemIdsState, currentItem.id])]
                                setExpandedItemIdsState(newExpandedIds)
                                onSetExpandedItemIds && onSetExpandedItemIds(newExpandedIds)
                            } else {
                                // If folder is already expanded, focus first child
                                const nextItem = visibleItems[currentIndex + 1]
                                if (nextItem) {
                                    setFocusedId(nextItem.id)
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
                        if (
                            currentItem?.children &&
                            currentItem?.children?.length >= 0 &&
                            expandedItemIdsState.includes(currentItem.id)
                        ) {
                            const newExpandedIds = expandedItemIdsState.filter((id) => id !== currentItem.id)
                            setExpandedItemIdsState(newExpandedIds)
                            onSetExpandedItemIds && onSetExpandedItemIds(newExpandedIds)
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
                            }
                        } else if (currentIndex < visibleItems.length - 1) {
                            setFocusedId(visibleItems[currentIndex + 1].id)
                            // setSelectedd(undefined)
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
                            }
                        } else if (currentIndex > 0) {
                            // Otherwise move focus to previous item
                            setFocusedId(visibleItems[currentIndex - 1].id)
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
                            if (currentItem.children && currentItem.children?.length >= 0) {
                                // Toggle folder expanded state
                                if (expandedItemIdsState.includes(currentItem.id)) {
                                    onFolderClick?.(currentItem, false)
                                    // Close folder by removing from expanded IDs
                                    setExpandedItemIdsState(expandedItemIdsState.filter((id) => id !== currentItem.id))
                                } else {
                                    onFolderClick?.(currentItem, true)
                                    // Open folder by adding to expanded IDs
                                    const newExpandedIds = [...new Set([...expandedItemIdsState, currentItem.id])]
                                    setExpandedItemIdsState(newExpandedIds)
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
                onNodeClick,
                onFolderClick,
                onSetExpandedItemIds,
                isNodeTreeContextMenuOpen,
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
            const SCROLL_PADDING = 64
            const isAboveFold = elementBounds.top - SCROLL_PADDING < containerBounds.top
            const isBelowFold = elementBounds.bottom + SCROLL_PADDING > containerBounds.bottom

            if (isAboveFold || isBelowFold) {
                element.scrollIntoView({
                    block: 'nearest',
                    behavior: 'smooth',
                })
            }
        }, [selectedId, focusedId])

        // Scroll to focused item when tree is finished building or prop is not provided
        useEffect(() => {
            if (isFinishedBuildingTreeData ?? true) {
                scrollFocusedIntoView()
            }
        }, [scrollFocusedIntoView, isFinishedBuildingTreeData])

        useEffect(() => {
            // On prop change, set focusedId if it's not already focused
            // if the content has been focused (via keyboard), don't focus the tree
            if (defaultSelectedFolderOrNodeId && !hasFocusedContent) {
                setFocusedId(defaultSelectedFolderOrNodeId)
                setSelectedId(defaultSelectedFolderOrNodeId)
            }
        }, [defaultSelectedFolderOrNodeId, hasFocusedContent])

        return (
            <DndContext onDragEnd={onDragEnd}>
                <ScrollableShadows
                    ref={containerRef}
                    direction="vertical"
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
                    <TreeNodeDroppable id="" isDroppable={enableDragAndDrop} className="h-full pb-32">
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
                            itemSideAction={itemSideAction}
                            className="deprecated-space-y-px"
                            isItemDraggable={isItemDraggable}
                            isItemDroppable={isItemDroppable}
                            enableDragAndDrop={enableDragAndDrop}
                            onContextMenuOpen={(open) => {
                                setIsNodeTreeContextMenuOpen(open)
                            }}
                            itemContextMenu={itemContextMenu}
                            {...props}
                        />
                    </TreeNodeDroppable>
                </ScrollableShadows>
            </DndContext>
        )
    }
)
LemonTree.displayName = 'LemonTree'

export { LemonTree }
