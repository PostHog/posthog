import { DndContext, DragEndEvent, DragOverlay, MouseSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import React, {
    CSSProperties,
    ForwardedRef,
    HTMLAttributes,
    forwardRef,
    useCallback,
    useEffect,
    useImperativeHandle,
    useRef,
    useState,
} from 'react'

import { IconEllipsis, IconUpload } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '../../ui/ContextMenu/ContextMenu'
import { SideAction } from '../LemonButton'
import { Link } from '../Link/Link'
import { Spinner } from '../Spinner/Spinner'
import {
    InlineEditField,
    TreeNodeDisplayCheckbox,
    TreeNodeDisplayIcon,
    TreeNodeDraggable,
    TreeNodeDroppable,
} from './LemonTreeUtils'

export type LemonTreeSelectMode = 'default' | 'multi' | 'folder-only' | 'all'
export type LemonTreeSize = 'default' | 'narrow'

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
    /** The icon to render for the item's side action. Ellipsis by default. */
    itemSideActionIcon?: (item: TreeDataItem) => React.ReactNode
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
    type?: 'node' | 'separator' | 'category' | 'empty-folder' | 'loading-indicator'

    /**
     * Handle a click on the item.
     * @param open - boolean to indicate if it's a folder and it's open state
     */
    onClick?: (open?: boolean) => void

    /** Tags for the item */
    tags?: string[]

    /** Order of object in tree */
    visualOrder?: number
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
        formatString?: (value: any, item?: TreeDataItem) => string
        /** Format function for the column */
        formatComponent?: (value: any, item?: TreeDataItem) => React.ReactNode
        /** Tooltip function for the column */
        tooltip?: string | ((value: any, item?: TreeDataItem) => React.ReactNode)
        /** Width of the column */
        width?: number
        /** Offset of the column */
        offset?: number
    }>
}

type LemonTreeBaseProps = Omit<HTMLAttributes<HTMLDivElement>, 'onDragEnd'> & {
    /** The mode of the tree. */
    mode?: TreeMode
    /** The data to render in the tree. */
    data: TreeDataItem[]
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
    /** The select mode of the tree. */
    selectMode?: LemonTreeSelectMode
    /** Whether the item is active, useful for highlighting the current item against a URL path,
     * this takes precedence over showFolderActiveState, and selectedId state */
    isItemActive?: (item: TreeDataItem) => boolean
    /** Whether the item is draggable */
    isItemDraggable?: (item: TreeDataItem) => boolean
    /** Whether the item can accept drops */
    isItemDroppable?: (item: TreeDataItem) => boolean
    /** The side action to render for the item. */
    itemSideAction?: (item: TreeDataItem) => React.ReactNode | undefined
    /** The button to render for the item's side action. */
    itemSideActionButton?: (item: TreeDataItem) => React.ReactNode
    /** The context menu to render for the item. */
    itemContextMenu?: (item: TreeDataItem) => React.ReactNode
    /** Whether the item is loading */
    isItemLoading?: (item: TreeDataItem) => boolean
    /** Whether the item is unapplied */
    isItemUnapplied?: (item: TreeDataItem) => boolean
    /** Whether the item is editing */
    isItemEditing?: (item: TreeDataItem) => boolean
    /** The function to call when the item name is changed. */
    onItemNameChange?: (item: TreeDataItem, name: string) => void
    /** The function to call when the item is checked. */
    onItemChecked?: (id: string, checked: boolean, shift: boolean) => void
    /** Count of checked items */
    checkedItemCount?: number
    /** The render function for the item. */
    renderItem?: (item: TreeDataItem, children: React.ReactNode) => React.ReactNode
    renderItemTooltip?: (item: TreeDataItem) => React.ReactNode | undefined
    renderItemIcon?: (item: TreeDataItem) => React.ReactNode | undefined
    /** Set the IDs of the expanded items. */
    onSetExpandedItemIds?: (ids: string[]) => void
    /** Pass true if you need to wait for async events to populate the tree.
     * If present and true will trigger: scrolling to focused item */
    isFinishedBuildingTreeData?: boolean
    /** The context menu to render for the empty space. */
    emptySpaceContextMenu?: () => React.ReactNode
    /** Set the focus to the element from the tree item ID. */
    setFocusToElementFromId?: (id: string) => void
    /** Set the focus to the last focused element. */
    setFocusToLastFocusedElement?: () => void
    /** The keys for the table view */
    tableViewKeys?: TreeTableViewKeys

    /** The width of the table columns */
    tableColumnWidths?: number[]

    /** The total width of the table */
    tableModeTotalWidth?: number

    /** The header to render for the table mode */
    tableModeHeader?: () => React.ReactNode
    /** The row to render for the table mode */
    tableModeRow?: (item: TreeDataItem, firstColumnOffset: number) => React.ReactNode

    /** The size of the tree.
     *
     * default: icon, text, side action visible
     *
     * narrow: icon, no text, side action hidden
     */
    size?: LemonTreeSize
}

export type LemonTreeProps = LemonTreeBaseProps & {
    /** Whether to expand all folders by default. Defaults to false. Disabled folders will not be expanded. */
    expandAllFolders?: boolean
    /** handler for folder clicks.*/
    onFolderClick?: (folder: TreeDataItem | undefined, isExpanded: boolean) => void
    /** handler for node clicks. */
    onItemClick?: (
        node: TreeDataItem | undefined,
        event: React.MouseEvent<HTMLElement> | React.KeyboardEvent<HTMLElement>
    ) => void
    /** The ref of the content to focus when the tree is clicked. TODO: make non-optional. */
    contentRef?: React.RefObject<HTMLElement>
    /** Handler for when a drag operation completes */
    onDragEnd?: (dragEvent: DragEndEvent) => void
    /** Whether the item is checked. */
    isItemChecked?: (item: TreeDataItem, checked: boolean) => boolean | undefined
    /** Whether to disable the scrollable shadows. */
    disableScroll?: boolean
}

export type LemonTreeNodeProps = LemonTreeBaseProps & {
    /** The ID of the item. */
    selectedId?: string
    /** Handle a click on the item. */
    handleClick: (
        item: TreeDataItem | undefined,
        isKeyboardAction: boolean,
        event: React.MouseEvent<HTMLElement> | React.KeyboardEvent<HTMLElement>
    ) => void
    /** The depth of the item. */
    depth?: number
    /** Tell <LemonTree> to disable keyboard input */
    disableKeyboardInput?: (disable: boolean) => void
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
            tableModeTotalWidth,
            tableModeRow,
            selectedId,
            handleClick,
            renderItem,
            renderItemTooltip,
            renderItemIcon,
            expandedItemIds,
            onSetExpandedItemIds,
            defaultNodeIcon,
            showFolderActiveState,
            isItemActive,
            isItemDraggable,
            isItemDroppable,
            depth = 0,
            itemSideAction,
            itemSideActionButton,
            isItemEditing,
            onItemNameChange,
            enableDragAndDrop = false,
            disableKeyboardInput,
            itemContextMenu,
            selectMode = 'default',
            onItemChecked,
            isDragging,
            checkedItemCount,
            setFocusToElementFromId,
            setFocusToLastFocusedElement,
            size,
            ...props
        },
        ref
    ): JSX.Element => {
        const DEPTH_OFFSET = 16 * depth

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

            // We want to focus the item when the context menu is open
            setFocusToElementFromId?.(itemId)

            // When the context menu is open, disable keyboard input in the tree
            disableKeyboardInput?.(open)
        }

        return (
            <div className={cn('flex flex-col gap-y-px list-none m-0 p-0 h-full w-full', className)}>
                {data.map((item, index) => {
                    const displayName = item.displayName ?? item.name
                    const isFolder = (item.children && item.children.length > 0) || item.record?.type === 'folder'
                    const isEmptyFolder = item.type === 'empty-folder'
                    const folderLinesOffset = DEPTH_OFFSET
                    const emptySpaceOffset = DEPTH_OFFSET

                    const firstColumnOffset =
                        selectMode === 'multi' && !item.disableSelect ? emptySpaceOffset + 24 : emptySpaceOffset

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
                                      const formattedValue = header.formatString
                                          ? header.formatString(value, item)
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
                    if (item.type === 'category') {
                        if (size !== 'default') {
                            return null
                        }
                        return (
                            <div key={item.id} className="not-first:mt-3 py-1 px-2 flex items-center">
                                <span className="text-xs font-semibold text-tertiary">{item.displayName}</span>
                            </div>
                        )
                    }

                    let button = (
                        <ContextMenu
                            onOpenChange={(open) => {
                                handleContextMenuOpen(open, item.id)
                            }}
                        >
                            {/* Folder lines */}
                            {depth !== 0 && size !== 'narrow' && (
                                <div
                                    className="folder-line absolute border-r border-primary h-[calc(100%+2px)] -top-px pointer-events-none z-0"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: `${folderLinesOffset}px` }}
                                />
                            )}

                            <ContextMenuTrigger asChild>
                                <Link
                                    data-id={item.id}
                                    data-attr={`menu-item-${item.name.toLowerCase().replace(/\s+/g, '-')}`}
                                    // When dragging, don't allow links to be clicked,
                                    // without this drag end would fire this href causing a reload
                                    to={item.disabledReason || isEmptyFolder ? '#' : item.record?.href || '#'}
                                    onClick={(e) => {
                                        if (item.disabledReason) {
                                            e.preventDefault()
                                        } else {
                                            handleClick(item, false, e)
                                        }
                                    }}
                                    disabled={isDragging}
                                    role="treeitem"
                                    buttonProps={{
                                        active: getItemActiveState(item),
                                        menuItem: true,
                                        hasSideActionRight: size === 'default',
                                        iconOnly: size === 'narrow',
                                        disabled: isEmptyFolder,
                                        className: cn(
                                            'group/lemon-tree-button gap-[5px]',
                                            'relative z-1 focus-visible:bg-fill-button-tertiary-hover motion-safe:transition-[padding] duration-50 h-[var(--lemon-tree-button-height)] [&_.icon-shortcut]:size-3',
                                            {
                                                'bg-fill-button-tertiary-hover':
                                                    ((selectMode === 'folder-only' || selectMode === 'all') &&
                                                        selectedId === item.id &&
                                                        !isEmptyFolder) ||
                                                    isContextMenuOpenForItem === item.id,
                                                'bg-fill-button-tertiary-active': getItemActiveState(item),
                                                'group-hover/lemon-tree-button-group:bg-fill-button-tertiary-hover cursor-pointer':
                                                    !isEmptyFolder,
                                                'hover:bg-transparent opacity-50 cursor-default':
                                                    (selectMode === 'folder-only' && !isFolder) || isEmptyFolder,
                                                'rounded-l-[var(--radius)] justify-center [&_svg]:size-4':
                                                    size === 'narrow',
                                            }
                                        ),
                                    }}
                                    tabIndex={isEmptyFolder ? -1 : 0}
                                    aria-level={depth + 1}
                                    aria-setsize={data.length} // TODO: somehow get all loaded items length here in children
                                    aria-posinset={index + 1}
                                    aria-selected={selectedId === item.id}
                                    aria-disabled={!!item.disabledReason}
                                    aria-haspopup={!!itemContextMenu?.(item)}
                                    aria-roledescription="tree item"
                                    aria-label={ariaLabel}
                                    tooltip={
                                        isDragging || isEmptyFolder || mode === 'table'
                                            ? undefined
                                            : renderItemTooltip?.(item)
                                    }
                                    tooltipPlacement="right"
                                >
                                    {size === 'default' && (
                                        <span
                                            // Spacer to offset button padding
                                            className="h-[var(--lemon-tree-button-height)] bg-transparent pointer-events-none flex-shrink-0 transition-[width] duration-50 -ml-1.5"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{
                                                width: `${firstColumnOffset}px`,
                                            }}
                                        />
                                    )}

                                    {renderItemIcon ? (
                                        renderItemIcon?.(item)
                                    ) : (
                                        <TreeNodeDisplayIcon
                                            item={item}
                                            expandedItemIds={expandedItemIds ?? []}
                                            defaultNodeIcon={defaultNodeIcon}
                                            size={size}
                                        />
                                    )}

                                    {size === 'default' && (
                                        <>
                                            {mode === 'table' ? (
                                                tableModeRow?.(item, firstColumnOffset)
                                            ) : (
                                                <span className="relative truncate text-left w-full">
                                                    {renderItem ? (
                                                        <>
                                                            {renderItem(
                                                                item,
                                                                <span
                                                                    className={cn({
                                                                        'font-semibold': isFolder && !isEmptyFolder,
                                                                    })}
                                                                >
                                                                    {displayName}
                                                                </span>
                                                            )}
                                                        </>
                                                    ) : (
                                                        <span
                                                            className={cn('truncate', {
                                                                'font-semibold': isFolder && !isEmptyFolder,
                                                            })}
                                                        >
                                                            {displayName}
                                                        </span>
                                                    )}

                                                    {/* Loading state */}
                                                    {item.record?.loading && <Spinner className="ml-1" />}

                                                    {/* Unapplied state */}
                                                    {item.record?.unapplied && (
                                                        <IconUpload className="ml-1 text-warning" />
                                                    )}
                                                </span>
                                            )}
                                        </>
                                    )}
                                </Link>
                            </ContextMenuTrigger>

                            {itemContextMenu?.(item) && (
                                <ContextMenuContent loop className="max-w-[250px]">
                                    {itemContextMenu(item)}
                                </ContextMenuContent>
                            )}
                        </ContextMenu>
                    )

                    if (enableDragAndDrop && isItemDraggable?.(item) && item.id) {
                        button = (
                            <TreeNodeDraggable
                                id={item.id}
                                enableDragging
                                className="h-[var(--lemon-tree-button-height)]"
                            >
                                {button}
                            </TreeNodeDraggable>
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
                                    <ButtonGroupPrimitive
                                        fullWidth
                                        className="group/lemon-tree-button-group relative h-[var(--lemon-tree-button-height)] bg-transparent"
                                    >
                                        <TreeNodeDisplayCheckbox
                                            item={item}
                                            handleCheckedChange={(checked, shift) => {
                                                onItemChecked?.(item.id, checked, shift)
                                            }}
                                            className={cn('absolute z-2', {
                                                // Hide checkbox when select mode is not multi
                                                hidden: selectMode !== 'multi',
                                            })}
                                            style={{
                                                left: `${firstColumnOffset - 20}px`,
                                            }}
                                        />

                                        {isItemEditing?.(item) ? (
                                            <InlineEditField
                                                value={item.name}
                                                handleSubmit={(value) => {
                                                    onItemNameChange?.(item, value)
                                                    disableKeyboardInput?.(false)
                                                }}
                                                className="z-1"
                                                style={{
                                                    width:
                                                        selectMode === 'multi' && !item.disableSelect
                                                            ? `${emptySpaceOffset + 26}px`
                                                            : `${emptySpaceOffset}px`,
                                                }}
                                                inputStyle={{
                                                    maxWidth:
                                                        mode === 'table'
                                                            ? `${tableViewKeys?.headers[0].width}px`
                                                            : undefined,
                                                }}
                                            >
                                                {renderItemIcon ? (
                                                    renderItemIcon?.(item)
                                                ) : (
                                                    <TreeNodeDisplayIcon
                                                        item={item}
                                                        expandedItemIds={expandedItemIds ?? []}
                                                        defaultNodeIcon={defaultNodeIcon}
                                                    />
                                                )}
                                            </InlineEditField>
                                        ) : (
                                            button
                                        )}

                                        {itemSideAction &&
                                            itemSideAction(item) !== undefined &&
                                            !isEmptyFolder &&
                                            size === 'default' && (
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild>
                                                        {itemSideActionButton?.(item) ?? (
                                                            <ButtonPrimitive
                                                                iconOnly
                                                                isSideActionRight
                                                                className="z-2 opacity-0 group-hover/lemon-tree-button-group:opacity-100 data-[state=open]:opacity-100 transition-opacity"
                                                            >
                                                                <IconEllipsis className="size-3 text-tertiary" />
                                                            </ButtonPrimitive>
                                                        )}
                                                    </DropdownMenuTrigger>

                                                    {/* The Dropdown content menu */}
                                                    {!!itemSideAction(item) && (
                                                        <DropdownMenuContent
                                                            loop
                                                            align="end"
                                                            side="bottom"
                                                            className="max-w-[250px]"
                                                        >
                                                            {itemSideAction(item)}
                                                        </DropdownMenuContent>
                                                    )}
                                                </DropdownMenu>
                                            )}
                                    </ButtonGroupPrimitive>
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
                                            renderItemTooltip={renderItemTooltip}
                                            renderItemIcon={renderItemIcon}
                                            itemSideAction={itemSideAction}
                                            depth={depth + 1}
                                            isItemActive={isItemActive}
                                            isItemDraggable={isItemDraggable}
                                            isItemDroppable={isItemDroppable}
                                            enableDragAndDrop={enableDragAndDrop}
                                            itemContextMenu={itemContextMenu}
                                            selectMode={selectMode}
                                            onItemChecked={onItemChecked}
                                            isDragging={isDragging}
                                            checkedItemCount={checkedItemCount}
                                            tableModeTotalWidth={tableModeTotalWidth}
                                            isItemEditing={isItemEditing}
                                            disableKeyboardInput={disableKeyboardInput}
                                            setFocusToElementFromId={setFocusToElementFromId}
                                            onItemNameChange={onItemNameChange}
                                            tableModeRow={tableModeRow}
                                            size={size}
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
            </div>
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
            onItemClick,
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
            isItemEditing,
            onItemNameChange,
            enableDragAndDrop = false,
            itemContextMenu,
            isFinishedBuildingTreeData,
            selectMode = 'default',
            onItemChecked,
            checkedItemCount = 0,
            tableViewKeys,
            emptySpaceContextMenu,
            tableModeTotalWidth,
            tableModeHeader,
            tableModeRow,
            size = 'default',
            disableScroll = false,
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
        const typeAheadTimeoutRef = useRef<NodeJS.Timeout>()

        // Scrollable container
        const containerRef = useRef<HTMLDivElement>(null)
        // Current state (when matching defaultSelectedFolderOrNodeId)
        const [selectedId, setSelectedId] = useState<string | undefined>(defaultSelectedFolderOrNodeId)
        const [hasFocusedContent, setHasFocusedContent] = useState(false)
        const [isDragging, setIsDragging] = useState(false)
        const [activeDragItem, setActiveDragItem] = useState<TreeDataItem | null>(null)
        const [disableKeyboardInput, setDisableKeyboardInput] = useState(false)
        const [typeAheadBuffer, setTypeAheadBuffer] = useState<string>('')

        // Add new state for type-ahead
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
                    // For folder-only mode, only include folders; for other modes, include all items
                    if (selectMode === 'folder-only') {
                        // Only include folders in folder-only mode
                        if (node.record?.type === 'folder' || node.children) {
                            items.push(node)
                        }
                    } else {
                        if (node.type !== 'separator' && node.type !== 'category') {
                            // Include all items in default/multi mode
                            items.push(node)
                        }
                    }
                    if (node.children && expandedItemIdsState?.includes(node.id)) {
                        traverse(node.children)
                    }
                })
            }

            traverse(data)
            return items
        }, [data, expandedItemIdsState, selectMode])

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
                // Disabled if context menu is open or an item is being edited
                if (disableKeyboardInput) {
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
                    const element = containerRef.current?.querySelector(
                        `[data-id="${CSS.escape(match.id)}"]`
                    ) as HTMLElement
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
                disableKeyboardInput,
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
                if (items[index].type !== 'separator' && items[index].type !== 'category') {
                    return items[index]
                }
            }
        }

        const handleClick = useCallback(
            (
                item: TreeDataItem | undefined,
                isKeyboardAction = false,
                event: React.MouseEvent<HTMLElement> | React.KeyboardEvent<HTMLElement>
            ): void => {
                const isFolder = (item?.children && item?.children?.length >= 0) || item?.record?.type === 'folder'

                // Handle click on a node
                if (!isFolder) {
                    if (onItemClick) {
                        onItemClick(item, event)
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

                if (selectMode === 'folder-only' || selectMode === 'all') {
                    setSelectedId(item?.id)
                }
            },
            [expandedItemIdsState, onFolderClick, onItemClick, focusContent, selectMode]
        )

        /** Focus the element from the tree item ID. */
        const focusElementFromId = useCallback((id: string) => {
            // Timeout to ensure the element is rendered
            setTimeout(() => {
                // Now use the escaped ID in your query
                const element = containerRef.current?.querySelector(`[data-id=${CSS.escape(id)}]`) as HTMLElement
                // Focus the element
                element?.focus()
            }, 100)
        }, [])

        // Update handleKeyDown to use native focus
        const handleKeyDown = useCallback(
            (e: React.KeyboardEvent<HTMLElement>) => {
                // Disabled if context menu is open or an item is being edited
                if (disableKeyboardInput) {
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
                                        `[data-id="${CSS.escape(nextItem.id)}"]`
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
                                    `[data-id="${CSS.escape(parentItem.id)}"]`
                                ) as HTMLElement
                                element?.focus()
                            } else {
                                // If parent is already collapsed, just focus it
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${CSS.escape(parentItem.id)}"]`
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
                            const firstItem = visibleItems.find(
                                (item) => item.type !== 'separator' && item.type !== 'category'
                            )
                            if (firstItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${CSS.escape(firstItem.id)}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        } else {
                            const nextItem = findNextFocusableItem(visibleItems, currentIndex, 1)
                            if (nextItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${CSS.escape(nextItem.id)}"]`
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
                            const lastItem = [...visibleItems]
                                .reverse()
                                .find((item) => item.type !== 'separator' && item.type !== 'category')
                            if (lastItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${CSS.escape(lastItem.id)}"]`
                                ) as HTMLElement
                                element?.focus()
                            }
                        } else {
                            const prevItem = findNextFocusableItem(visibleItems, currentIndex, -1)
                            if (prevItem) {
                                const element = containerRef.current?.querySelector(
                                    `[data-id="${CSS.escape(prevItem.id)}"]`
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
                                `[data-id="${CSS.escape(visibleItems[0].id)}"]`
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
                                `[data-id="${CSS.escape(visibleItems[visibleItems.length - 1].id)}"]`
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
                                if (onItemClick) {
                                    // Otherwise use default node click handler
                                    onItemClick(currentItem, e)

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
                onItemClick,
                onFolderClick,
                onSetExpandedItemIds,
                disableKeyboardInput,
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
            const element = containerRef.current.querySelector(`[data-id="${CSS.escape(elementId)}"]`)
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
                    `[data-id="${CSS.escape(defaultSelectedFolderOrNodeId)}"]`
                ) as HTMLElement
                element?.focus()
                setSelectedId(defaultSelectedFolderOrNodeId)
            }
        }, [defaultSelectedFolderOrNodeId, hasFocusedContent])

        useImperativeHandle(ref, () => ({
            getVisibleItems,
            focusItem: (id: string) => {
                // Find and focus the actual DOM element
                const element = containerRef.current?.querySelector(`[data-id="${CSS.escape(id)}"]`) as HTMLElement
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
                <ScrollableShadows
                    ref={containerRef}
                    direction="vertical"
                    tabIndex={-1}
                    role="tree"
                    aria-label="Tree navigation"
                    onKeyDown={handleKeyDown}
                    className="flex-1"
                    innerClassName="relative overflow-x-auto"
                    disableScroll={disableScroll}
                    hideShadows={disableScroll}
                    styledScrollbars
                    style={
                        {
                            // for scrollable shadows
                            '--scrollable-shadows-offset-top': mode === 'table' ? '30px' : '0px',
                            // for tree element
                            '--lemon-tree-button-height': 'var(--button-height-base)',
                            '--lemon-tree-button-icon-offset-top': '5px',
                        } as CSSProperties
                    }
                >
                    {mode === 'table' && (
                        <div
                            className="sticky top-0 z-20 border-b border-primary bg-surface-secondary starting:h-0 h-[30px] motion-safe:transition-all [transition-behavior:allow-discrete] duration-500"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: mode === 'table' ? `${tableModeTotalWidth}px` : undefined,
                            }}
                        >
                            {tableModeHeader?.()}
                        </div>
                    )}

                    <TreeNodeDroppable
                        id=""
                        isDroppable={enableDragAndDrop}
                        isRoot
                        isDragging={isDragging}
                        style={{
                            width: mode === 'table' ? `${tableModeTotalWidth}px` : undefined,
                        }}
                    >
                        <LemonTreeNode
                            data={data}
                            mode={mode}
                            tableViewKeys={tableViewKeys}
                            tableModeTotalWidth={tableModeTotalWidth}
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
                            isItemEditing={isItemEditing}
                            onItemNameChange={onItemNameChange}
                            className={cn('p-1', {
                                'flex-1': isDragging,
                            })}
                            isItemDraggable={isItemDraggable}
                            isItemDroppable={isItemDroppable}
                            enableDragAndDrop={enableDragAndDrop}
                            disableKeyboardInput={(disable) => {
                                setDisableKeyboardInput(disable)
                            }}
                            itemContextMenu={itemContextMenu}
                            selectMode={selectMode}
                            onItemChecked={onItemChecked}
                            isDragging={isDragging}
                            checkedItemCount={checkedItemCount}
                            setFocusToElementFromId={focusElementFromId}
                            tableModeRow={tableModeRow}
                            size={size}
                            {...props}
                        />
                    </TreeNodeDroppable>

                    {/* Context menu for empty space, takes up remaining space */}
                    <div
                        className={cn('flex-1 w-full h-full absolute top-0 left-0 z-1', {
                            hidden: isDragging,
                        })}
                    >
                        <ContextMenu>
                            <ContextMenuTrigger className="flex-1 w-full h-full">
                                <div className="h-full w-full" />
                            </ContextMenuTrigger>
                            <ContextMenuContent>{emptySpaceContextMenu?.()}</ContextMenuContent>
                        </ContextMenu>
                    </div>
                </ScrollableShadows>

                {/* Custom drag overlay */}
                <DragOverlay dropAnimation={null}>
                    {activeDragItem && (
                        <ButtonPrimitive className="min-w-[var(--project-panel-inner-width)] ">
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
