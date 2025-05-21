import { IconCheckbox, IconChevronRight, IconFolder, IconFolderPlus, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { moveToLogic } from 'lib/components/MoveTo/moveToLogic'
import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { dayjs } from 'lib/dayjs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, TreeDataItem, TreeMode } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { RefObject, useEffect, useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { UserBasicType } from '~/types'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic, ProjectTreeSortMethod } from './projectTreeLogic'
import { calculateMovePath } from './utils'

export interface ProjectTreeProps {
    logicKey?: string // key override?
    sortMethod?: ProjectTreeSortMethod // default: "folder"
    root?: string
    onlyTree?: boolean
}

export const PROJECT_TREE_KEY = 'project-tree'

export function ProjectTree({ logicKey, sortMethod, root, onlyTree }: ProjectTreeProps): JSX.Element {
    const { treeItemsNew, viableItems } = useValues(projectTreeDataLogic)
    const { setLastNewFolder } = useActions(projectTreeDataLogic)
    const {
        fullFileSystemFiltered,
        treeTableKeys,
        lastViewedId,
        expandedFolders,
        expandedSearchFolders,
        searchTerm,
        searchResults,
        checkedItems,
        checkedItemsCount,
        checkedItemCountNumeric,
        scrollTargetId,
        editingItemId,
        checkedItemsArray,
        treeTableColumnSizes,
        treeTableTotalWidth,
        sortMethod: projectSortMethod,
        selectMode,
    } = useValues(projectTreeLogic({ key: logicKey ?? PROJECT_TREE_KEY, root }))
    const {
        createFolder,
        rename,
        deleteItem,
        moveItem,
        toggleFolderOpen,
        setLastViewedId,
        setExpandedFolders,
        setExpandedSearchFolders,
        loadFolder,
        onItemChecked,
        moveCheckedItems,
        linkCheckedItems,
        setCheckedItems,
        assureVisibility,
        clearScrollTarget,
        setEditingItemId,
        setSortMethod,
        setTreeTableColumnSizes,
        setSelectMode,
        setSearchTerm,
        clearSearch,
    } = useActions(projectTreeLogic({ key: logicKey ?? PROJECT_TREE_KEY, root }))
    const { openMoveToModal } = useActions(moveToLogic)
    const { addShortcutItem } = useActions(shortcutsLogic)

    const { showLayoutPanel, setPanelTreeRef, clearActivePanelIdentifier, setProjectTreeMode } =
        useActions(panelLayoutLogic)
    const { mainContentRef, isLayoutPanelPinned, projectTreeMode } = useValues(panelLayoutLogic)
    const treeRef = useRef<LemonTreeRef>(null)

    useEffect(() => {
        setPanelTreeRef(treeRef)
    }, [treeRef, setPanelTreeRef])

    useEffect(() => {
        if (projectSortMethod !== (sortMethod ?? 'folder')) {
            setSortMethod(sortMethod ?? 'folder')
        }
    }, [sortMethod, projectSortMethod])

    // When logic requests a scroll, focus the item and clear the request
    useEffect(() => {
        if (scrollTargetId && treeRef.current) {
            treeRef.current.focusItem(scrollTargetId)
            setLastViewedId(scrollTargetId) // keeps selection in sync
            clearScrollTarget()
        }
    }, [scrollTargetId, treeRef, clearScrollTarget, setLastViewedId])

    // Merge duplicate menu code for both context and dropdown menus
    const renderMenuItems = (item: TreeDataItem, type: 'context' | 'dropdown'): JSX.Element => {
        // Determine the separator component based on MenuItem type
        const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem
        const MenuSeparator = type === 'context' ? ContextMenuSeparator : DropdownMenuSeparator
        const MenuSub = type === 'context' ? ContextMenuSub : DropdownMenuSub
        const MenuSubTrigger = type === 'context' ? ContextMenuSubTrigger : DropdownMenuSubTrigger
        const MenuSubContent = type === 'context' ? ContextMenuSubContent : DropdownMenuSubContent

        return (
            <>
                {item.record?.path && !item.disableSelect ? (
                    <>
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                onItemChecked(item.id, !checkedItems[item.id], false)
                            }}
                        >
                            <ButtonPrimitive menuItem>{checkedItems[item.id] ? 'Deselect' : 'Select'}</ButtonPrimitive>
                        </MenuItem>

                        <MenuSeparator />
                    </>
                ) : null}

                {item.record?.path && item.record?.type !== 'folder' && item.record?.href ? (
                    <>
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                window.open(item.record?.href, '_blank')
                            }}
                        >
                            <ButtonPrimitive menuItem>Open link in new tab</ButtonPrimitive>
                        </MenuItem>
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                void navigator.clipboard.writeText(document.location.origin + item.record?.href)
                            }}
                        >
                            <ButtonPrimitive menuItem>Copy link address</ButtonPrimitive>
                        </MenuItem>
                        <MenuSeparator />
                    </>
                ) : null}

                {checkedItemCountNumeric > 0 && item.record?.type === 'folder' ? (
                    <>
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                moveCheckedItems(item?.record?.path)
                            }}
                        >
                            <ButtonPrimitive menuItem>
                                Move {checkedItemsCount} selected item{checkedItemsCount === '1' ? '' : 's'} here
                            </ButtonPrimitive>
                        </MenuItem>
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                linkCheckedItems(item?.record?.path)
                            }}
                        >
                            <ButtonPrimitive menuItem>
                                Create {checkedItemsCount} shortcut{checkedItemsCount === '1' ? '' : 's'} here
                            </ButtonPrimitive>
                        </MenuItem>

                        <MenuSeparator />
                    </>
                ) : null}

                {item.record?.type === 'folder' || item.id?.startsWith('project-folder-empty/') ? (
                    <>
                        <MenuSub key="new">
                            <MenuSubTrigger asChild>
                                <ButtonPrimitive menuItem>
                                    New...
                                    <IconChevronRight className="ml-auto h-4 w-4" />
                                </ButtonPrimitive>
                            </MenuSubTrigger>
                            <MenuSubContent>
                                <MenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        createFolder(item.record?.path)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>
                                        <IconFolder />
                                        Folder
                                    </ButtonPrimitive>
                                </MenuItem>
                                <MenuSeparator />
                                {treeItemsNew.map((treeItem): JSX.Element => {
                                    if (treeItem.children) {
                                        return (
                                            <MenuSub key={treeItem.id}>
                                                <MenuSubTrigger asChild inset>
                                                    <ButtonPrimitive menuItem>
                                                        {treeItem.name ||
                                                            treeItem.id.charAt(0).toUpperCase() + treeItem.id.slice(1)}
                                                        ...
                                                        <IconChevronRight className="ml-auto h-4 w-4" />
                                                    </ButtonPrimitive>
                                                </MenuSubTrigger>
                                                <MenuSubContent>
                                                    {treeItem.children.map((child) => (
                                                        <MenuItem
                                                            key={child.id}
                                                            asChild
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                const folder = item.record?.path
                                                                if (folder) {
                                                                    setLastNewFolder(folder)
                                                                }
                                                                if (child.record?.href) {
                                                                    router.actions.push(
                                                                        typeof child.record.href === 'function'
                                                                            ? child.record.href(child.record.ref)
                                                                            : child.record.href
                                                                    )
                                                                }
                                                            }}
                                                        >
                                                            <ButtonPrimitive menuItem className="capitalize">
                                                                {child.icon}
                                                                {child.name}
                                                            </ButtonPrimitive>
                                                        </MenuItem>
                                                    ))}
                                                </MenuSubContent>
                                            </MenuSub>
                                        )
                                    }
                                    return (
                                        <MenuItem
                                            key={treeItem.id}
                                            asChild
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                const folder = item.record?.path
                                                if (folder) {
                                                    setLastNewFolder(folder)
                                                }
                                                if (treeItem.record?.href) {
                                                    router.actions.push(
                                                        typeof treeItem.record.href === 'function'
                                                            ? treeItem.record.href(treeItem.record.ref)
                                                            : treeItem.record.href
                                                    )
                                                }
                                            }}
                                        >
                                            <ButtonPrimitive menuItem>
                                                {treeItem.icon}
                                                {treeItem.name}
                                            </ButtonPrimitive>
                                        </MenuItem>
                                    )
                                })}
                            </MenuSubContent>
                        </MenuSub>

                        <MenuSeparator />
                    </>
                ) : null}

                {item.record?.path && item.record?.type !== 'folder' && item.record?.href ? (
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            item.record && addShortcutItem(item.record as FileSystemEntry)
                        }}
                    >
                        <ButtonPrimitive menuItem>Add to shortcuts panel</ButtonPrimitive>
                    </MenuItem>
                ) : null}

                <MenuItem
                    asChild
                    onClick={(e: any) => {
                        e.stopPropagation()
                        if (
                            checkedItemsArray.length > 0 &&
                            checkedItemsArray.find(({ id }) => id === item.record?.id)
                        ) {
                            openMoveToModal(checkedItemsArray)
                        } else {
                            openMoveToModal([item.record as unknown as FileSystemEntry])
                        }
                    }}
                >
                    <ButtonPrimitive menuItem>Move to...</ButtonPrimitive>
                </MenuItem>
                {item.record?.path && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            setEditingItemId(item.id)
                        }}
                    >
                        <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                    </MenuItem>
                ) : null}

                {item.record?.path && item.record?.shortcut ? (
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            assureVisibility({ type: item.record?.type, ref: item.record?.ref })
                        }}
                    >
                        <ButtonPrimitive menuItem>Show original</ButtonPrimitive>
                    </MenuItem>
                ) : null}

                {item.record?.shortcut ? (
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            deleteItem(item.record as unknown as FileSystemEntry, logicKey ?? PROJECT_TREE_KEY)
                        }}
                    >
                        <ButtonPrimitive menuItem>Delete shortcut</ButtonPrimitive>
                    </MenuItem>
                ) : item.record?.path && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            deleteItem(item.record as unknown as FileSystemEntry, logicKey ?? PROJECT_TREE_KEY)
                        }}
                    >
                        <ButtonPrimitive menuItem>Delete folder</ButtonPrimitive>
                    </MenuItem>
                ) : null}
            </>
        )
    }

    const tree = (
        <LemonTree
            ref={treeRef}
            contentRef={mainContentRef as RefObject<HTMLElement>}
            className="px-0 py-1"
            data={fullFileSystemFiltered}
            mode={projectTreeMode as TreeMode}
            selectMode={selectMode}
            tableViewKeys={treeTableKeys}
            defaultSelectedFolderOrNodeId={lastViewedId || undefined}
            isItemActive={(item) => {
                if (!item.record?.href) {
                    return false
                }
                return window.location.href.endsWith(item.record?.href)
            }}
            onItemChecked={onItemChecked}
            checkedItemCount={checkedItemCountNumeric}
            onItemClick={(item) => {
                if (item?.type === 'empty-folder' || item?.type === 'loading-indicator') {
                    return
                }
                if (item?.record?.href) {
                    router.actions.push(
                        typeof item.record.href === 'function' ? item.record.href(item.record.ref) : item.record.href
                    )
                }
                if (!isLayoutPanelPinned || projectTreeMode === 'table') {
                    clearActivePanelIdentifier()
                    showLayoutPanel(false)
                }

                if (item?.record?.path) {
                    setLastViewedId(item?.id || '')
                }
                if (item?.id.startsWith('project-load-more/')) {
                    const path = item.id.split('/').slice(1).join('/')
                    if (path) {
                        loadFolder(path)
                    }
                }
            }}
            onFolderClick={(folder, isExpanded) => {
                if (folder) {
                    toggleFolderOpen(folder?.id || '', isExpanded)
                }
            }}
            isItemEditing={(item) => {
                return editingItemId === item.id
            }}
            onItemNameChange={(item, name) => {
                if (item.name !== name) {
                    rename(name, item.record as unknown as FileSystemEntry)
                }
                // Clear the editing item id when the name changes
                setEditingItemId('')
            }}
            expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
            onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
            enableDragAndDrop={!sortMethod || sortMethod === 'folder'}
            onDragEnd={(dragEvent) => {
                const itemToId = (item: FileSystemEntry): string =>
                    item.type === 'folder' ? 'project-folder/' + item.path : 'project/' + item.id
                const oldId = dragEvent.active.id as string
                const newId = dragEvent.over?.id
                if (oldId === newId) {
                    return false
                }

                const items = searchTerm && searchResults.results ? searchResults.results : viableItems
                const oldItem = items.find((i) => itemToId(i) === oldId)
                const newItem = items.find((i) => itemToId(i) === newId)
                if (oldItem === newItem || !oldItem) {
                    return false
                }

                const folder = newItem
                    ? newItem.path || ''
                    : newId && String(newId).startsWith('project-folder/')
                    ? String(newId).substring(15)
                    : ''

                if (checkedItems[oldId]) {
                    moveCheckedItems(folder)
                } else {
                    const { newPath, isValidMove } = calculateMovePath(oldItem, folder)
                    if (isValidMove) {
                        moveItem(oldItem, newPath, false, logicKey ?? PROJECT_TREE_KEY)
                    }
                }
            }}
            isItemDraggable={(item) => {
                return (item.id.startsWith('project/') || item.id.startsWith('project-folder/')) && item.record?.path
            }}
            isItemDroppable={(item) => {
                const path = item.record?.path || ''

                // disable dropping for these IDS
                if (!item.id.startsWith('project-folder/')) {
                    return false
                }

                // hacky, if the item has a href, it should not be droppable
                if (item.record?.href) {
                    return false
                }

                if (path) {
                    return true
                }
                return false
            }}
            itemContextMenu={(item) => {
                if (item.id.startsWith('project-folder-empty/')) {
                    return undefined
                }
                return <ContextMenuGroup>{renderMenuItems(item, 'context')}</ContextMenuGroup>
            }}
            itemSideAction={(item) => {
                if (item.id.startsWith('project-folder-empty/')) {
                    return undefined
                }
                return <DropdownMenuGroup>{renderMenuItems(item, 'dropdown')}</DropdownMenuGroup>
            }}
            emptySpaceContextMenu={() => {
                return (
                    <ContextMenuGroup>
                        <ContextMenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                createFolder('')
                            }}
                        >
                            <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                        </ContextMenuItem>
                    </ContextMenuGroup>
                )
            }}
            tableModeTotalWidth={treeTableTotalWidth}
            tableModeHeader={() => {
                return (
                    <>
                        {/* Headers */}
                        {treeTableKeys?.headers.map((header, index) => (
                            <ResizableElement
                                key={header.key}
                                defaultWidth={header.width || 0}
                                onResize={(width) => {
                                    setTreeTableColumnSizes([
                                        ...treeTableColumnSizes.slice(0, index),
                                        width,
                                        ...treeTableColumnSizes.slice(index + 1),
                                    ])
                                }}
                                className="absolute h-[30px] flex items-center"
                                style={{
                                    transform: `translateX(${header.offset || 0}px)`,
                                }}
                                aria-label={`Resize handle for column "${header.title}"`}
                            >
                                <ButtonPrimitive
                                    key={header.key}
                                    fullWidth
                                    className="pointer-events-none rounded-none text-secondary font-bold text-xs uppercase flex gap-2 motion-safe:transition-[left] duration-50"
                                    style={{
                                        paddingLeft: index === 0 ? '35px' : undefined,
                                    }}
                                >
                                    <span>{header.title}</span>
                                </ButtonPrimitive>
                            </ResizableElement>
                        ))}
                    </>
                )
            }}
            tableModeRow={(item, firstColumnOffset) => {
                return (
                    <>
                        {treeTableKeys?.headers.slice(0).map((header, index) => {
                            const width = header.width || 0
                            const offset = header.offset || 0
                            const value = header.key.split('.').reduce((obj, key) => (obj as any)?.[key], item)

                            // subtracting 48px is for offsetting the icon width and gap and padding... forgive me
                            const widthAdjusted = width - (index === 0 ? firstColumnOffset + 48 : 0)
                            const offsetAdjusted = index === 0 ? offset : offset - 12

                            return (
                                <span
                                    key={header.key}
                                    className="text-left flex items-center h-[var(--button-height-base)]"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        // First we keep relative
                                        position: index === 0 ? 'relative' : 'absolute',
                                        transform: `translateX(${offsetAdjusted}px)`,
                                        // First column we offset for the icons
                                        width: `${widthAdjusted}px`,
                                        paddingLeft: index !== 0 ? '6px' : undefined,
                                    }}
                                >
                                    <Tooltip
                                        title={
                                            typeof header.tooltip === 'function'
                                                ? header.tooltip(value)
                                                : header.tooltip
                                        }
                                        placement="top-start"
                                    >
                                        <span className="starting:opacity-0 opacity-100 delay-50 motion-safe:transition-opacity duration-100 font-normal truncate">
                                            {header.formatComponent
                                                ? header.formatComponent(value, item)
                                                : header.formatString
                                                ? header.formatString(value, item)
                                                : value}
                                        </span>
                                    </Tooltip>
                                </span>
                            )
                        })}
                    </>
                )
            }}
            renderItemTooltip={(item) => {
                const user = item.record?.user as UserBasicType | undefined

                return projectTreeMode === 'tree' ? (
                    <>
                        Name: <span className="font-semibold">{item.displayName}</span> <br />
                        Created by:{' '}
                        <ProfilePicture
                            user={user || { first_name: 'PostHog' }}
                            size="xs"
                            showName
                            className="font-semibold"
                        />
                        <br />
                        Created at:{' '}
                        <span className="font-semibold">
                            {dayjs(item.record?.created_at).format('MMM D, YYYY h:mm A')}
                        </span>
                    </>
                ) : undefined
            }}
            renderItemIcon={(item) => {
                return (
                    <>
                        {sortMethod === 'recent' && projectTreeMode === 'tree' && item.type !== 'loading-indicator' && (
                            <ProfilePicture
                                user={item.record?.user as UserBasicType | undefined}
                                size="xs"
                                className="ml-[4px]"
                            />
                        )}
                        <TreeNodeDisplayIcon
                            item={item}
                            expandedItemIds={expandedFolders}
                            defaultNodeIcon={<IconFolder />}
                        />
                    </>
                )
            }}
            renderItem={(item) => {
                return (
                    <span className="truncate">
                        <span
                            className={cn('truncate', {
                                'font-semibold': item.record?.type === 'folder' && item.type !== 'empty-folder',
                            })}
                        >
                            {item.displayName}
                        </span>
                        {sortMethod === 'recent' && projectTreeMode === 'tree' && item.type !== 'loading-indicator' && (
                            <span className="text-tertiary text-xxs pt-[3px] ml-1">
                                {dayjs(item.record?.created_at).fromNow()}
                            </span>
                        )}
                    </span>
                )
            }}
        />
    )

    if (onlyTree) {
        return tree
    }

    return (
        <PanelLayoutPanel
            searchTerm={searchTerm}
            setSearchTerm={setSearchTerm}
            clearSearch={clearSearch}
            showFilterDropdown={true}
            searchPlaceholder={sortMethod === 'recent' ? 'Search recent items' : 'Search your project'}
            panelActions={
                <>
                    {sortMethod !== 'recent' ? (
                        <ButtonPrimitive onClick={() => createFolder('')} tooltip="New root folder" iconOnly>
                            <IconFolderPlus className="text-tertiary" />
                        </ButtonPrimitive>
                    ) : null}

                    {selectMode === 'default' && checkedItemCountNumeric === 0 ? (
                        <ButtonPrimitive onClick={() => setSelectMode('multi')} tooltip="Enable multi-select" iconOnly>
                            <IconCheckbox className="text-tertiary size-4" />
                        </ButtonPrimitive>
                    ) : (
                        <>
                            {checkedItemCountNumeric > 0 && checkedItemsCount !== '0+' ? (
                                <ButtonPrimitive
                                    onClick={() => {
                                        setCheckedItems({})
                                        setSelectMode('default')
                                    }}
                                    tooltip="Clear selected and disable multi-select"
                                >
                                    <LemonTag type="highlight">{checkedItemsCount} selected</LemonTag>
                                </ButtonPrimitive>
                            ) : (
                                <ButtonPrimitive
                                    onClick={() => setSelectMode('default')}
                                    tooltip="Disable multi-select"
                                    iconOnly
                                >
                                    <IconX className="text-tertiary size-4" />
                                </ButtonPrimitive>
                            )}
                        </>
                    )}
                </>
            }
        >
            <ButtonPrimitive
                tooltip={projectTreeMode === 'tree' ? 'Switch to table view' : 'Switch to tree view'}
                onClick={() => setProjectTreeMode(projectTreeMode === 'tree' ? 'table' : 'tree')}
                className="absolute top-1/2 translate-y-1/2 right-0 translate-x-1/2 w-fit bg-surface-primary border border-primary z-[var(--z-resizer)]"
            >
                <IconChevronRight
                    className={cn('size-4', {
                        'rotate-180': projectTreeMode === 'table',
                        'rotate-0': projectTreeMode === 'tree',
                    })}
                />
            </ButtonPrimitive>

            <div role="status" aria-live="polite" className="sr-only">
                Sorted {sortMethod === 'recent' ? 'by creation date' : 'alphabetically'}
            </div>

            {tree}
        </PanelLayoutPanel>
    )
}
