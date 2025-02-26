import { IconChevronRight } from '@posthog/icons'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { cn } from 'lib/utils/css-classes'
import { forwardRef, HTMLAttributes, useCallback, useRef, useState } from 'react'

import { LemonButton, SideAction } from '../LemonButton'

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
    /**
     * Handle a click on the item.
     * @param open - boolean to indicate if it's a folder and it's open state
     */
    onClick?: (open?: boolean) => void
}

export type LemonTreeNodeProps = LemonTreeProps & {
    /** The ID of the item. */
    selectedId?: string
    /** The ID of the focused item. */
    focusedId?: string
    /** Handle a click on the item. */
    handleClick: (item: TreeDataItem | undefined) => void
    /** The render function for the item. */
    renderItem?: (item: TreeDataItem, children: React.ReactNode) => React.ReactNode
    /** The IDs of the expanded items. */
    expandedItemIds: string[]
    /** Set the IDs of the expanded items. */
    setExpandedItemIds: (ids: string[]) => void
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
            setExpandedItemIds,
            defaultNodeIcon,
            showFolderActiveState,
            itemSideAction,
        },
        ref
    ): JSX.Element => {
        const ICON_CLASSES = 'size-6 aspect-square flex place-items-center'

        if (!(data instanceof Array)) {
            data = [data]
        }

        // Get the node or folder icon
        // If no icon is provided, use a defaultNodeIcon icon
        // If no defaultNodeIcon icon is provided, use empty div
        function getIcon(item: TreeDataItem, expandedItemIds: string[]): JSX.Element {
            if (item.children) {
                return (
                    <span className={ICON_CLASSES}>
                        <IconChevronRight
                            className={cn(
                                'transition-transform scale-75 stroke-2',
                                expandedItemIds.includes(item.id) ? 'rotate-90' : ''
                            )}
                        />
                    </span>
                )
            }

            return (
                <span
                    className={cn(ICON_CLASSES, {
                        'text-secondary': item.disabledReason,
                    })}
                >
                    {item.icon || defaultNodeIcon || <div className={ICON_CLASSES} />}
                </span>
            )
        }

        return (
            <ul className={cn('list-none m-0 p-0', className)} role="group">
                {data.map((item) => (
                    <AccordionPrimitive.Root
                        type="multiple"
                        value={expandedItemIds}
                        onValueChange={(s) => setExpandedItemIds(s)}
                        ref={ref}
                        key={item.id}
                        disabled={!!item.disabledReason}
                    >
                        <AccordionPrimitive.Item value={item.id} className="flex flex-col w-full">
                            <AccordionPrimitive.Trigger className="flex items-center gap-2 w-full h-8" asChild>
                                <LemonButton
                                    className={cn('flex-1 flex items-center gap-2 cursor-pointer pl-0 font-normal')}
                                    onClick={() => handleClick(item)}
                                    type={selectedId === item.id ? 'secondary' : 'tertiary'}
                                    role="treeitem"
                                    tabIndex={-1}
                                    size="small"
                                    fullWidth
                                    active={
                                        focusedId === item.id ||
                                        selectedId === item.id ||
                                        (showFolderActiveState && item.children && expandedItemIds.includes(item.id))
                                    }
                                    icon={getIcon(item, expandedItemIds)}
                                    disabledReason={item.disabledReason}
                                    tooltipPlacement="right"
                                    sideAction={itemSideAction ? itemSideAction(item) : undefined}
                                >
                                    <span
                                        className={cn('', {
                                            'font-semibold': selectedId === item.id,
                                            'text-secondary': item.disabledReason,
                                        })}
                                    >
                                        {renderItem ? renderItem(item, item.name) : item.name}
                                    </span>
                                </LemonButton>
                            </AccordionPrimitive.Trigger>

                            {item.children && (
                                <AccordionPrimitive.Content>
                                    <LemonTreeNode
                                        data={item.children}
                                        selectedId={selectedId}
                                        focusedId={focusedId}
                                        handleClick={handleClick}
                                        expandedItemIds={expandedItemIds}
                                        setExpandedItemIds={setExpandedItemIds}
                                        defaultNodeIcon={defaultNodeIcon}
                                        showFolderActiveState={showFolderActiveState}
                                        itemSideAction={itemSideAction}
                                        renderItem={renderItem}
                                        className="ml-4 space-y-px"
                                    />
                                </AccordionPrimitive.Content>
                            )}
                        </AccordionPrimitive.Item>
                    </AccordionPrimitive.Root>
                ))}
            </ul>
        )
    }
)
LemonTreeNode.displayName = 'LemonTreeNode'

export type LemonTreeProps = HTMLAttributes<HTMLDivElement> & {
    /** The data to render in the tree. */
    data: TreeDataItem[] | TreeDataItem
    /** The ID of the folder/node to select by default. Will expand the node if it has children. */
    defaultSelectedFolderOrNodeId?: string
    /** Whether to expand all folders by default. Defaults to false. Disabled folders will not be expanded. */
    expandAllFolders?: boolean
    /** The icon to use for node items. Defaults to <IconChevronRight />. */
    defaultNodeIcon?: React.ReactNode
    /** Whether to show an active state on folder nodes when selected. Defaults to false. */
    showFolderActiveState?: boolean
    /** The render function for the item. */
    renderItem?: (item: TreeDataItem, children: React.ReactNode) => React.ReactNode
    /** handler for folder clicks.
     * @param folder - the folder that was clicked
     */
    onFolderClick?: (folder: TreeDataItem | undefined) => void
    /** handler for node clicks.
     * @param node - the node that was clicked
     */
    onNodeClick?: (node: TreeDataItem | undefined) => void
    /** The side action to render for the item. */
    itemSideAction?: (item: TreeDataItem) => SideAction

    /** The ref of the content to focus when the tree is clicked. TODO: make non-optional. */
    contentRef?: React.RefObject<HTMLElement>
}

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
            itemSideAction,
            ...props
        },
        ref
    ): JSX.Element => {
        const TYPE_AHEAD_TIMEOUT = 500

        const [selectedId, setSelectedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        const [focusedId, setFocusedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        // Add new state for type-ahead
        const [typeAheadBuffer, setTypeAheadBuffer] = useState<string>('')
        const typeAheadTimeoutRef = useRef<NodeJS.Timeout>()

        function collectAllIds(items: TreeDataItem[] | TreeDataItem, allIds: string[]): void {
            if (items instanceof Array) {
                items.forEach((item) => {
                    if (!item.disabledReason) {
                        allIds.push(item.id)
                    }
                    if (item.children) {
                        collectAllIds(item.children, allIds)
                    }
                })
            } else {
                if (!items.disabledReason) {
                    allIds.push(items.id)
                }
                if (items.children) {
                    collectAllIds(items.children, allIds)
                }
            }
        }

        const [expandedItemIds, setExpandedItemIds] = useState<string[]>((): string[] => {
            if (expandAllFolders) {
                // If expandAll is true, collect all item IDs
                const allIds: string[] = []
                collectAllIds(data, allIds)
                return allIds
            }

            if (!defaultSelectedFolderOrNodeId) {
                return []
            }

            // If not expandAll, only expand path to selected item
            const ids: string[] = []
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
            walkTreeItems(data, defaultSelectedFolderOrNodeId)
            return ids
        })

        // Flatten visible tree items for keyboard navigation
        const getVisibleItems = useCallback((): TreeDataItem[] => {
            const items: TreeDataItem[] = []

            const traverse = (nodes: TreeDataItem[] | TreeDataItem): void => {
                const nodeArray = nodes instanceof Array ? nodes : [nodes]

                nodeArray.forEach((node) => {
                    items.push(node)
                    if (node.children && expandedItemIds.includes(node.id)) {
                        traverse(node.children)
                    }
                })
            }

            traverse(data)
            return items
        }, [data, expandedItemIds])

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
                        setExpandedItemIds([...new Set([...expandedItemIds, ...path])])
                    }
                }
            },
            [typeAheadBuffer, focusedId, getVisibleItems, data, expandedItemIds, findPathToItem]
        )

        const handleClick = useCallback(
            (item: TreeDataItem | undefined): void => {
                // Update focusedId when clicking
                setFocusedId(item?.id)

                // Handle click on a node
                if (!item?.children) {
                    if (onNodeClick) {
                        setSelectedId(item?.id)
                        onNodeClick(item)
                        focusContent() // Add focus content here as well
                    }
                } else if (onFolderClick) {
                    // Handle click on a folder
                    onFolderClick(item)
                }
                if (item?.onClick) {
                    // Handle custom click handler for a folder/ node, pass true if it's a folder and it's not open (yet)
                    const willBeOpen = item?.children ? !expandedItemIds.includes(item.id) : undefined
                    item.onClick(willBeOpen)
                }
            },
            [expandedItemIds, onFolderClick, onNodeClick, focusContent]
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
                            if (!expandedItemIds.includes(currentItem.id)) {
                                setExpandedItemIds([...expandedItemIds, currentItem.id])
                            } else {
                                // If folder is already expanded, focus first child
                                const nextItem = visibleItems[currentIndex + 1]
                                if (nextItem) {
                                    setFocusedId(nextItem.id)
                                    setSelectedId(undefined)
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

                        if (currentItem?.children && expandedItemIds.includes(currentItem.id)) {
                            // If current item is an expanded folder, collapse it
                            setExpandedItemIds(expandedItemIds.filter((id) => id !== currentItem.id))
                            setFocusedId(currentItem.id)
                        } else {
                            // Otherwise find and focus parent folder
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
                            const parentItem = findParent(Array.isArray(data) ? data : [data], currentItem.id)
                            if (parentItem) {
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
                            setSelectedId(undefined)
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
                            setSelectedId(undefined)
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
                                handleClick(currentItem)

                                // Toggle folder expanded state
                                if (expandedItemIds.includes(currentItem.id)) {
                                    // Close folder by removing from expanded IDs
                                    setExpandedItemIds(expandedItemIds.filter((id) => id !== currentItem.id))
                                } else {
                                    // Open folder by adding to expanded IDs
                                    setExpandedItemIds([...expandedItemIds, currentItem.id])
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

                                    focusContent() // Use the new focusContent function
                                }
                            }
                        }
                        break
                    }
                }
            },
            [focusedId, expandedItemIds, getVisibleItems, handleTypeAhead, data, focusContent, handleClick, onNodeClick]
        )

        return (
            <div
                className={cn('overflow-hidden relative p-2', className)}
                tabIndex={0}
                role="tree"
                aria-label="Tree navigation"
                onKeyDown={handleKeyDown}
                onBlur={() => setFocusedId(undefined)}
            >
                <LemonTreeNode
                    data={data}
                    ref={ref}
                    selectedId={selectedId}
                    focusedId={focusedId}
                    handleClick={handleClick}
                    expandedItemIds={expandedItemIds}
                    setExpandedItemIds={setExpandedItemIds}
                    defaultNodeIcon={defaultNodeIcon}
                    showFolderActiveState={showFolderActiveState}
                    itemSideAction={itemSideAction}
                    className="space-y-px"
                    {...props}
                />
            </div>
        )
    }
)
LemonTree.displayName = 'LemonTree'

export { LemonTree }
