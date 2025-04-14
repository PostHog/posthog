import { DndContext, DragEndEvent, DragOverlay, MouseSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core'
import { IconEllipsis, IconUpload } from '@posthog/icons'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import {
    ForwardedRef,
    forwardRef,
    HTMLAttributes,
    useCallback,
    useEffect,
    useImperativeHandle,
    useRef,
    useState,
} from 'react'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '../../ui/ContextMenu/ContextMenu'
import { SideAction } from '../LemonButton'
import { Spinner } from '../Spinner/Spinner'
import { Tooltip } from '../Tooltip/Tooltip'
import { TreeNodeDisplayIcon, TreeNodeDisplayIconWrapper, TreeNodeDraggable, TreeNodeDroppable } from './LemonTreeUtils'

export type TreeDataItem = {
    /** The ID of the item. */
    id: string
    /** The name of the item. */
    name: string
    /** What to show as the name. */
    displayName?: React.ReactElement
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
    /** Prevent this item from being selected */
    disableSelect?: boolean
    /** Is the item selected */
    checked?: boolean | 'indeterminate'
    /** The icon to use for the side action. */
    sideIcon?: React.ReactNode

    /** The type of item.
     *
     * Type node, normal behavior
     * Type separator, render as separator
     */
    type?: 'node' | 'separator' | 'empty-folder'

    /**
     * Handle a click on the item.
     * @param open - boolean to indicate if it's a folder and it's open state
     */
    onClick?: (open?: boolean) => void
}
export type TreeMode = 'tree' | 'table'

export type TreeTableViewKeys = {
    /** The headers for the table view */
    headers: Array<{
        /** Unique key for the column */
        key: string
        /** Display title for the column */
        title: string
        /** Format function for the column */
        formatFunction?: (value: any) => string
        /** Tooltip function for the column */
        tooltip?: string | ((value: any) => string)
    }>
}

type LemonTreeBaseProps = Omit<HTMLAttributes<HTMLDivElement>, 'onDragEnd'> & {
    /** The mode of the tree. */
    mode?: TreeMode
    /** The data to render in the tree. */
    data: TreeDataItem[]
    /** The keys for the table view */
    tableViewKeys?: TreeTableViewKeys
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
    /** Whether to enable multi-selection. */
    enableMultiSelection?: boolean
    /** Whether the item is active, useful for highlighting the current item against a URL path,
     * this takes precedence over showFolderActiveState, and selectedId state */
    isItemActive?: (item: TreeDataItem) => boolean
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
    /** The function to call when the item is checked. */
    onItemChecked?: (id: string, checked: boolean) => void
    /** Count of checked items */
    checkedItemCount?: number
    /** The render function for the item. */
    renderItem?: (item: TreeDataItem, children: React.ReactNode) => React.ReactNode
    /** Set the IDs of the expanded items. */
    onSetExpandedItemIds?: (ids: string[]) => void
    /** Pass true if you need to wait for async events to populate the tree.
     * If present and true will trigger: scrolling to focused item */
    isFinishedBuildingTreeData?: boolean
    /** The context menu to render for the empty space. */
    emptySpaceContextMenu?: () => React.ReactNode
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
    /** Whether the item is checked. */
    isItemChecked?: (item: TreeDataItem, checked: boolean) => boolean | undefined
}

export type LemonTreeNodeProps = LemonTreeBaseProps & {
    /** The ID of the item. */
    selectedId?: string
    /** Handle a click on the item. */
    handleClick: (item: TreeDataItem | undefined, isKeyboardAction?: boolean) => void
    /** The depth of the item. */
    depth?: number
    /** Whether the context menu is open */
    onContextMenuOpen?: (open: boolean) => void
    /** Whether the item is dragging */
    isDragging?: boolean
}

export interface LemonTreeRef {
    getVisibleItems: () => TreeDataItem[]
    focusItem: (id: string) => void
}

const LemonTreeNode = forwardRef<HTMLDivElement, LemonTreeNodeProps>(
    (
        {
            className,
            data,
            mode,
            tableViewKeys,
            selectedId,
            handleClick,
            renderItem,
            expandedItemIds,
            onSetExpandedItemIds,
            defaultNodeIcon,
            showFolderActiveState,
            isItemActive,
            isItemDraggable,
            isItemDroppable,
            depth = 0,
            itemSideAction,
            enableDragAndDrop = false,
            onContextMenuOpen,
            itemContextMenu,
            enableMultiSelection = false,
            onItemChecked,
            isDragging,
            checkedItemCount,
            ...props
        },
        ref
    ): JSX.Element => {
        const DEPTH_OFFSET = depth === 0 ? 0 : 16 * depth

        const [isContextMenuOpenForItem, setIsContextMenuOpenForItem] = useState<string | undefined>(undefined)

        const getItemActiveState = (item: TreeDataItem): boolean => {
            if (typeof isItemActive === 'function') {
                return isItemActive(item)
            }
            return Boolean(
                selectedId === item.id || (showFolderActiveState && item.children && expandedItemIds?.includes(item.id))
            )
        }

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
                {data.map((item, index) => {
                    const displayName = item.displayName ?? item.name
                    const isFolder = item.record?.type === 'folder'
                    const isEmptyFolder = item.type === 'empty-folder'

                    // If table mode, renders: "tree item: Name: My App Dashboard, Created at: Mar 28, 2025, Created by: Adam etc"
                    // If empty folder, renders: "empty folder"
                    // If tree mode, renders: "tree item: My App Dashboard"
                    const ariaLabel =
                        mode === 'table' && tableViewKeys
                            ? `tree item: ${tableViewKeys?.headers
                                  .map((header) => {
                                      const value = header.key
                                          .split('.')
                                          .reduce((obj, key) => (obj as any)?.[key], item)
                                      const formattedValue = header.formatFunction
                                          ? header.formatFunction(value)
                                          : value
                                      // Add null/undefined check and handle object values properly
                                      const displayValue =
                                          formattedValue === null || formattedValue === undefined
                                              ? ''
                                              : typeof formattedValue === 'object'
                                              ? JSON.stringify(formattedValue)
                                              : String(formattedValue)
                                      return `${header.title}: ${displayValue}`
                                  })
                                  .join(', ')}`
                            : isEmptyFolder
                            ? 'empty folder'
                            : `tree item: ${item.name}`

                    if (item.type === 'separator') {
                        return (
                            <div key={item.id} className="h-1 -mx-2 flex items-center">
                                <div className="border-b border-primary h-px my-2 flex-1" />
                            </div>
                        )
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
                            <AccordionPrimitive.Item value={item.id} className="flex flex-col w-full gap-y-px">
                                <AccordionPrimitive.Trigger className="flex items-center gap-2 w-full h-8" asChild>
                                    <ContextMenu
                                        onOpenChange={(open) => {
                                            handleContextMenuOpen(open, item.id)
                                        }}
                                    >
                                        {/* Folder lines */}
                                        {depth !== 0 && (
                                            <div
                                                className="folder-line absolute border-r border-primary h-[calc(100%+2px)] -top-px pointer-events-none z-0"
                                                // eslint-disable-next-line react/forbid-dom-props
                                                style={{ width: `${DEPTH_OFFSET}px` }}
                                            />
                                        )}

                                        <ContextMenuTrigger asChild>
                                            <ButtonGroupPrimitive
                                                fullWidth
                                                className="group/lemon-tree-button-group relative h-[var(--button-height-base)]"
                                                groupVariant="side-action-group"
                                            >
                                                {/* The contents of this <TreeNodeDisplayIconWrapper> are positioned absolutely, so to give the effect it's inside the button */}
                                                {!isEmptyFolder && (
                                                    <TreeNodeDisplayIconWrapper
                                                        item={item}
                                                        expandedItemIds={expandedItemIds}
                                                        defaultNodeIcon={defaultNodeIcon}
                                                        handleClick={handleClick}
                                                        enableMultiSelection={enableMultiSelection}
                                                        depthOffset={DEPTH_OFFSET}
                                                        checkedItemCount={checkedItemCount}
                                                        onItemChecked={onItemChecked}
                                                    />
                                                )}

                                                <ButtonPrimitive
                                                    data-id={item.id}
                                                    // When dragging, don't allow links to be clicked,
                                                    // without this drag end would fire this href causing a reload
                                                    href={isDragging ? undefined : item.record?.href}
                                                    onClick={() => {
                                                        handleClick(item)
                                                    }}
                                                    className={cn(
                                                        'group/lemon-tree-button',
                                                        'pl-8 z-1 focus-visible:bg-fill-button-tertiary-hover h-[var(--button-height-base)] motion-safe:transition-[padding] duration-50',
                                                        {
                                                            'bg-fill-button-tertiary-hover':
                                                                selectedId === item.id ||
                                                                isContextMenuOpenForItem === item.id,
                                                            'bg-fill-button-tertiary-active': getItemActiveState(item),
                                                            'pl-13': enableMultiSelection,
                                                            'pl-4 italic text-tertiary pointer-events-none cursor-default h-[var(--button-height-base)]':
                                                                isEmptyFolder,
                                                            'group-hover/lemon-tree-button-group:bg-fill-button-tertiary-hover cursor-pointer':
                                                                !isEmptyFolder,
                                                        }
                                                    )}
                                                    role="treeitem"
                                                    active={getItemActiveState(item)}
                                                    menuItem
                                                    sideActionLeft
                                                    tooltip={
                                                        isDragging || isEmptyFolder || mode === 'table'
                                                            ? undefined
                                                            : displayName
                                                    }
                                                    tooltipPlacement="right"
                                                    disabled={isEmptyFolder}
                                                    tabIndex={isEmptyFolder ? -1 : 0}
                                                    buttonWrapper={
                                                        enableDragAndDrop && isItemDraggable?.(item) && item.id
                                                            ? (button) => (
                                                                  <TreeNodeDraggable
                                                                      id={item.id}
                                                                      enableDragging
                                                                      className="h-[var(--button-height-base)]"
                                                                  >
                                                                      {button}
                                                                  </TreeNodeDraggable>
                                                              )
                                                            : undefined
                                                    }
                                                    aria-level={depth + 1}
                                                    aria-setsize={data.length} // TODO: somehow get all loaded items length here in children
                                                    aria-posinset={index + 1}
                                                    aria-selected={selectedId === item.id}
                                                    aria-disabled={!!item.disabledReason}
                                                    aria-haspopup={!!itemContextMenu?.(item)}
                                                    aria-roledescription="tree item"
                                                    aria-rolemap={`item-${item.id}`}
                                                    aria-label={ariaLabel}
                                                >
                                                    {/* Spacer to offset button padding */}
                                                    {depth !== 0 && (
                                                        <div
                                                            className="h-full bg-transparent pointer-events-none flex-shrink-0"
                                                            // -6 is to offset button padding (to match folder lines)
                                                            // eslint-disable-next-line react/forbid-dom-props
                                                            style={{
                                                                width: `${DEPTH_OFFSET - 6}px`,
                                                            }}
                                                        />
                                                    )}

                                                    {/* Render contents */}
                                                    <span
                                                        className={cn('truncate w-full text-left', {
                                                            'grid gap-2': mode === 'table',
                                                        })}
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        style={{
                                                            gridTemplateColumns:
                                                                mode === 'table'
                                                                    ? `repeat(${tableViewKeys?.headers.length}, minmax(100px, 265px))`
                                                                    : undefined,
                                                        }}
                                                    >
                                                        {renderItem ? (
                                                            <>
                                                                {renderItem(
                                                                    item,
                                                                    <span
                                                                        className={cn('xxxxx', {
                                                                            'font-semibold': isFolder,
                                                                        })}
                                                                    >
                                                                        <Tooltip
                                                                            title={
                                                                                mode === 'table'
                                                                                    ? displayName
                                                                                    : undefined
                                                                            }
                                                                            placement="top-start"
                                                                            className="w-fit"
                                                                        >
                                                                            <span>{displayName}</span>
                                                                        </Tooltip>
                                                                    </span>
                                                                )}
                                                            </>
                                                        ) : (
                                                            <span
                                                                className={cn('yyyyyy', {
                                                                    'font-semibold': isFolder && !isEmptyFolder,
                                                                })}
                                                            >
                                                                <Tooltip
                                                                    title={mode === 'table' ? displayName : undefined}
                                                                    placement="top-start"
                                                                    className="w-fit"
                                                                >
                                                                    <span>{displayName}</span>
                                                                </Tooltip>
                                                            </span>
                                                        )}

                                                        {/* Loading state */}
                                                        {item.record?.loading && <Spinner className="ml-1" />}

                                                        {/* Unapplied state */}
                                                        {item.record?.unapplied && (
                                                            <IconUpload className="ml-1 text-warning" />
                                                        )}
                                                        {mode === 'table' &&
                                                            tableViewKeys?.headers.slice(1).map((header, index) => {
                                                                const value = header.key
                                                                    .split('.')
                                                                    .reduce((obj, key) => (obj as any)?.[key], item)

                                                                return (
                                                                    <span
                                                                        key={header.key}
                                                                        className="truncate text-left"
                                                                    >
                                                                        <Tooltip
                                                                            title={
                                                                                typeof header.tooltip === 'function'
                                                                                    ? header.tooltip(value)
                                                                                    : header.tooltip
                                                                            }
                                                                            placement="top-start"
                                                                        >
                                                                            <span
                                                                                className={cn(
                                                                                    'starting:opacity-0 opacity-100 delay-50 motion-safe:transition-opacity duration-100',
                                                                                    {
                                                                                        'font-normal':
                                                                                            index !== 0 &&
                                                                                            !isEmptyFolder,
                                                                                        'font-semibold':
                                                                                            index === 0 &&
                                                                                            (isFolder ||
                                                                                                (isFolder &&
                                                                                                    !isEmptyFolder)),
                                                                                        'opacity-0':
                                                                                            index !== 0 &&
                                                                                            isEmptyFolder,
                                                                                    }
                                                                                )}
                                                                            >
                                                                                {header.formatFunction
                                                                                    ? header.formatFunction(value)
                                                                                    : value}
                                                                            </span>
                                                                        </Tooltip>
                                                                    </span>
                                                                )
                                                            })}
                                                    </span>
                                                </ButtonPrimitive>

                                                {itemSideAction && !isEmptyFolder && (
                                                    <DropdownMenu>
                                                        <DropdownMenuTrigger asChild>
                                                            <ButtonPrimitive
                                                                iconOnly
                                                                sideActionRight
                                                                className="z-2 shrink-0 motion-safe:transition-opacity duration-[50ms] group-hover/lemon-tree-button-group:opacity-100 aria-expanded:opacity-100"
                                                            >
                                                                <IconEllipsis className="size-3 text-tertiary" />
                                                            </ButtonPrimitive>
                                                        </DropdownMenuTrigger>

                                                        {/* The Dropdown content menu */}
                                                        <DropdownMenuContent
                                                            loop
                                                            align="end"
                                                            side="bottom"
                                                            className="max-w-[250px]"
                                                        >
                                                            {itemSideAction(item)}
                                                        </DropdownMenuContent>
                                                    </DropdownMenu>
                                                )}
                                            </ButtonGroupPrimitive>
                                        </ContextMenuTrigger>

                                        {isContextMenuOpenForItem === item.id && itemContextMenu?.(item) ? (
                                            <ContextMenuContent loop className="max-w-[250px]">
                                                {itemContextMenu(item)}
                                            </ContextMenuContent>
                                        ) : null}
                                    </ContextMenu>
                                </AccordionPrimitive.Trigger>

                                {item.children && (
                                    <AccordionPrimitive.Content className="relative">
                                        <LemonTreeNode
                                            data={item.children}
                                            mode={mode}
                                            tableViewKeys={tableViewKeys}
                                            selectedId={selectedId}
                                            handleClick={handleClick}
                                            expandedItemIds={expandedItemIds}
                                            onSetExpandedItemIds={onSetExpandedItemIds}
                                            defaultNodeIcon={defaultNodeIcon}
                                            showFolderActiveState={showFolderActiveState}
                                            renderItem={renderItem}
                                            itemSideAction={itemSideAction}
                                            className="deprecated-space-y-px"
                                            depth={depth + 1}
                                            isItemActive={isItemActive}
                                            isItemDraggable={isItemDraggable}
                                            isItemDroppable={isItemDroppable}
                                            enableDragAndDrop={enableDragAndDrop}
                                            onContextMenuOpen={onContextMenuOpen}
                                            itemContextMenu={itemContextMenu}
                                            enableMultiSelection={enableMultiSelection}
                                            onItemChecked={onItemChecked}
                                            isDragging={isDragging}
                                            checkedItemCount={checkedItemCount}
                                            {...props}
                                        />
                                    </AccordionPrimitive.Content>
                                )}
                            </AccordionPrimitive.Item>
                        </AccordionPrimitive.Root>
                    )

                    // Wrap content in Draggable/Droppable if needed
                    let wrappedContent = content

                    if (isItemDroppable?.(item)) {
                        wrappedContent = (
                            <TreeNodeDroppable id={item.id} isDroppable={item.record?.type === 'folder'}>
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

const LemonTree = forwardRef<LemonTreeRef, LemonTreeProps>(
    (
        {
            data,
            mode,
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
            enableMultiSelection = false,
            onItemChecked,
            checkedItemCount,
            emptySpaceContextMenu,
            tableViewKeys,
            ...props
        },
        ref: ForwardedRef<LemonTreeRef>
    ): JSX.Element => {
        const TYPE_AHEAD_TIMEOUT = 500
        const mouseSensor = useSensor(MouseSensor, {
            // Require the mouse to move by 10 pixels before activating
            activationConstraint: {
                distance: 10,
            },
        })
        const touchSensor = useSensor(TouchSensor, {
            // Press delay of 250ms, with tolerance of 5px of movement
            activationConstraint: {
                delay: 250,
                tolerance: 5,
            },
        })
        const sensors = useSensors(mouseSensor, touchSensor)

        // Scrollable container
        const containerRef = useRef<HTMLDivElement>(null)

        // Current state (when matching defaultSelectedFolderOrNodeId)
        const [selectedId, setSelectedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        const [hasFocusedContent, setHasFocusedContent] = useState(false)
        const [isDragging, setIsDragging] = useState(false)
        const [activeDragItem, setActiveDragItem] = useState<TreeDataItem | null>(null)

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
                const currentElement = document.activeElement
                const currentId = currentElement?.getAttribute('data-id')
                const currentIndex = visibleItems.findIndex((item) => item.id === currentId)

                // Start search from item after current focus, wrapping to start if needed
                const searchItems = [
                    ...visibleItems.slice(currentIndex + 1),
                    ...visibleItems.slice(0, currentIndex + 1),
                ]

                const match = searchItems.find((item) => item.name.toLowerCase().startsWith(newBuffer))

                if (match) {
                    // Focus the matching element
                    const element = containerRef.current?.querySelector(`[data-id="${match.id}"]`) as HTMLElement
                    element?.focus()

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
                getVisibleItems,
                data,
                findPathToItem,
                onSetExpandedItemIds,
                expandedItemIdsState,
                isNodeTreeContextMenuOpen,
            ]
        )

        // Helper function to find next/previous non-separator item
        const findNextFocusableItem = (
            items: TreeDataItem[],
            currentIndex: number,
            direction: 1 | -1
        ): TreeDataItem | undefined => {
            let index = currentIndex
            while (true) {
                index += direction
                if (direction > 0 && index >= items.length) {
                    return undefined
                }
                if (direction < 0 && index < 0) {
                    return undefined
                }
                if (items[index].type !== 'separator') {
                    return items[index]
                }
            }
        }

        const handleClick = useCallback(
            (item: TreeDataItem | undefined, isKeyboardAction = false): void => {
                const isFolder = (item?.children && item?.children?.length >= 0) || item?.record?.type === 'folder'

                // Handle click on a node
                if (!isFolder) {
                    if (onNodeClick) {
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

        // Update handleKeyDown to use native focus
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
                const currentElement = document.activeElement
                const currentId = currentElement?.getAttribute('data-id')
                const currentIndex = visibleItems.findIndex((item) => item.id === currentId)

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
                                onFolderClick?.(currentItem, false)
                                const newExpandedIds = [...new Set([...expandedItemIdsState, currentItem.id])]
                                setExpandedItemIdsState(newExpandedIds)
                                onSetExpandedItemIds && onSetExpandedItemIds(newExpandedIds)
                            } else {
                                // If folder is already expanded, focus first child
                                const nextItem = visibleItems[currentIndex + 1]
                                if (nextItem) {
                                    const element = containerRef.current?.querySelector(
                                        `[data-id="${nextItem.id}"]`
                                    ) as HTMLElement
                                    element?.focus()
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
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${parentItem.id}"]`
                                ) as HTMLElement
                                element?.focus()
                            } else {
                                // If parent is already collapsed, just focus it
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${parentItem.id}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        }
                        break
                    }

                    // Down Arrow:
                    // Moves focus to the next node that is focusable without opening or closing a node.
                    case 'ArrowDown': {
                        e.preventDefault()
                        if (currentIndex === -1) {
                            // If no item is focused, focus the first non-separator item
                            const firstItem = visibleItems.find((item) => item.type !== 'separator')
                            if (firstItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${firstItem.id}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        } else {
                            const nextItem = findNextFocusableItem(visibleItems, currentIndex, 1)
                            if (nextItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${nextItem.id}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        }
                        break
                    }

                    // Up Arrow:
                    // Moves focus to the previous node that is focusable without opening or closing a node.
                    case 'ArrowUp': {
                        e.preventDefault()
                        if (currentIndex === -1) {
                            // If no item is focused, focus the last non-separator item
                            const lastItem = [...visibleItems].reverse().find((item) => item.type !== 'separator')
                            if (lastItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${lastItem.id}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        } else {
                            const prevItem = findNextFocusableItem(visibleItems, currentIndex, -1)
                            if (prevItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${prevItem.id}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        }
                        break
                    }

                    // Home:
                    // Moves focus to the first node in the tree that is focusable without opening a node.
                    case 'Home': {
                        e.preventDefault()
                        const visibleItems = getVisibleItems()
                        if (visibleItems.length > 0) {
                            const element = containerRef.current?.querySelector(
                                `[data-id="${visibleItems[0].id}"]`
                            ) as HTMLElement
                            element?.focus()
                        }
                        break
                    }

                    // End:
                    // Moves focus to the last node in the tree that is focusable without opening a node.
                    case 'End': {
                        e.preventDefault()
                        const visibleItems = getVisibleItems()
                        if (visibleItems.length > 0) {
                            const element = containerRef.current?.querySelector(
                                `[data-id="${visibleItems[visibleItems.length - 1].id}"]`
                            ) as HTMLElement
                            element?.focus()
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
            const elementId = selectedId
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
        }, [selectedId])

        // Scroll to focused item when tree is finished building or prop is not provided
        useEffect(() => {
            if (isFinishedBuildingTreeData ?? true) {
                scrollFocusedIntoView()
            }
        }, [scrollFocusedIntoView, isFinishedBuildingTreeData])

        useEffect(() => {
            // On prop change, focus the default selected item if content hasn't been focused
            if (defaultSelectedFolderOrNodeId && !hasFocusedContent) {
                const element = containerRef.current?.querySelector(
                    `[data-id="${defaultSelectedFolderOrNodeId}"]`
                ) as HTMLElement
                element?.focus()
                setSelectedId(defaultSelectedFolderOrNodeId)
            }
        }, [defaultSelectedFolderOrNodeId, hasFocusedContent])

        useImperativeHandle(ref, () => ({
            getVisibleItems,
            focusItem: (id: string) => {
                // Find and focus the actual DOM element
                const element = containerRef.current?.querySelector(`[data-id="${id}"]`) as HTMLElement
                element?.focus()
            },
        }))

        useEffect(() => {
            if (expandedItemIds && expandedItemIds.join(',') !== expandedItemIdsState.join(',')) {
                setExpandedItemIdsState(expandedItemIds ?? [])
            }
        }, [expandedItemIds, expandedItemIdsState])

        const findItem = (items: TreeDataItem[], itemId: string): TreeDataItem | undefined => {
            for (const item of items) {
                if (item.id === itemId) {
                    return item
                } else if (item.children) {
                    const found = findItem(item.children, itemId)
                    if (found) {
                        return found
                    }
                }
            }
            return undefined
        }

        return (
            <DndContext
                sensors={sensors}
                onDragStart={(event) => {
                    setIsDragging(true)
                    const item = findItem(data, String(event.active?.id))
                    if (item) {
                        setActiveDragItem(item)
                    }
                }}
                onDragEnd={(dragEvent) => {
                    const active = dragEvent.active?.id
                    const over = dragEvent.over?.id
                    if (active && active === over) {
                        dragEvent.activatorEvent.stopPropagation()
                    } else {
                        onDragEnd?.(dragEvent)
                    }
                    setIsDragging(false)
                }}
            >
                <div
                    className={cn(
                        'overflow-hidden motion-safe:transition-[height,display] duration-200 starting:h-0 [transition-behavior:allow-discrete]',
                        {
                            'hidden h-0 opacity-0': mode === 'tree' || !tableViewKeys,
                            'h-[30px] opacity-100 flex items-center px-1 border-b border-primary':
                                mode === 'table' && tableViewKeys,
                        }
                    )}
                >
                    <div
                        className="grid gap-2 pl-8 pr-[calc(var(--button-height-base)+var(--button-padding-x-base))] px-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            gridTemplateColumns: `repeat(${tableViewKeys?.headers.length ?? 0}, minmax(100px, 265px))`,
                        }}
                    >
                        {/* Headers */}
                        {tableViewKeys?.headers.map((header, index) => (
                            <div
                                key={header.key}
                                className={cn('text-secondary font-bold text-xs uppercase flex gap-2', {
                                    'pl-px': index === 0,
                                })}
                            >
                                <span>{header.title}</span>
                            </div>
                        ))}
                    </div>
                </div>

                <ScrollableShadows
                    ref={containerRef}
                    direction="vertical"
                    tabIndex={-1}
                    role="tree"
                    aria-label="Tree navigation"
                    onKeyDown={handleKeyDown}
                    className="flex-1"
                    innerClassName="p-1"
                    styledScrollbars
                >
                    <TreeNodeDroppable id="" isDroppable={enableDragAndDrop} className="h-full">
                        <LemonTreeNode
                            data={data}
                            mode={mode}
                            tableViewKeys={tableViewKeys}
                            selectedId={selectedId}
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
                            enableMultiSelection={enableMultiSelection}
                            onItemChecked={onItemChecked}
                            isDragging={isDragging}
                            checkedItemCount={checkedItemCount}
                            {...props}
                        />

                        {/* Context menu for empty space, takes up remaining space */}
                        <ContextMenu>
                            <ContextMenuTrigger className="flex-1 w-full">
                                <div className="h-full w-full" />
                            </ContextMenuTrigger>
                            <ContextMenuContent>{emptySpaceContextMenu?.()}</ContextMenuContent>
                        </ContextMenu>
                    </TreeNodeDroppable>
                </ScrollableShadows>

                {/* Custom drag overlay */}
                <DragOverlay dropAnimation={null}>
                    {activeDragItem && (
                        <ButtonPrimitive className="min-w-[var(--project-panel-inner-width)]">
                            <div className="shrink-0">
                                <TreeNodeDisplayIcon
                                    item={activeDragItem}
                                    expandedItemIds={expandedItemIdsState}
                                    defaultNodeIcon={defaultNodeIcon}
                                />
                            </div>
                            <span className="truncate font-medium">
                                {activeDragItem.displayName || activeDragItem.name}
                            </span>
                            {activeDragItem.checked && checkedItemCount && checkedItemCount > 1 && (
                                <span className="ml-1 text-xs rounded-full bg-primary-highlight px-2 py-0.5 whitespace-nowrap">
                                    +<span>{checkedItemCount - 1}</span>{' '}
                                    <span>other{checkedItemCount - 1 === 1 ? '' : 's'}</span>
                                </span>
                            )}
                        </ButtonPrimitive>
                    )}
                </DragOverlay>
            </DndContext>
        )
    }
)
LemonTree.displayName = 'LemonTree'

export { LemonTree }
