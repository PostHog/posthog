import { IconChevronRight, IconFolderPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, TreeMode, TreeTableViewKeys } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { RefObject, useEffect, useMemo, useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree(): JSX.Element {
    const {
        treeData,
        lastViewedId,
        viableItems,
        expandedFolders,
        expandedSearchFolders,
        searchTerm,
        treeItemsNew,
        checkedItems,
        checkedItemsCount,
        checkedItemCountNumeric,
    } = useValues(projectTreeLogic)

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
        setLastNewOperation,
        onItemChecked,
        moveCheckedItems,
        linkCheckedItems,
        deleteCheckedItems,
        setCheckedItems,
        assureVisibility,
    } = useActions(projectTreeLogic)

    const { showLayoutPanel, setPanelTreeRef, clearActivePanelIdentifier, setProjectTreeMode } =
        useActions(panelLayoutLogic)
    const { mainContentRef, isLayoutPanelPinned, projectTreeMode } = useValues(panelLayoutLogic)
    const treeRef = useRef<LemonTreeRef>(null)

    const handleCopyPath = (path?: string): void => {
        if (path) {
            void navigator.clipboard.writeText(path)
        }
    }

    const getTableViewKeys = useMemo(
        (): TreeTableViewKeys => ({
            headers: [
                {
                    key: 'name',
                    title: 'Name',
                    tooltip: (value: string) => value,
                },
                {
                    key: 'record.created_at',
                    title: 'Created at',
                    formatFunction: (value: string) => dayjs(value).format('MMM D, YYYY'),
                    tooltip: (value: string) => dayjs(value).format('MMM D, YYYY HH:mm:ss'),
                },
                {
                    key: 'record.created_by.first_name',
                    title: 'Created by',
                    tooltip: (value: string) => value,
                },
            ],
        }),
        [treeData]
    )

    useEffect(() => {
        setPanelTreeRef(treeRef)
    }, [treeRef, setPanelTreeRef])

    // Merge duplicate menu code for both context and dropdown menus
    const renderMenuItems = (item: any, MenuItem: typeof ContextMenuItem | typeof DropdownMenuItem): JSX.Element => {
        // Determine the separator component based on MenuItem type
        const MenuSeparator = MenuItem === ContextMenuItem ? ContextMenuSeparator : DropdownMenuSeparator

        return (
            <>
                {item.record?.path ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            onItemChecked(item.id, !checkedItems[item.id])
                        }}
                    >
                        <ButtonPrimitive menuItem>{checkedItems[item.id] ? 'Deselect' : 'Select'}</ButtonPrimitive>
                    </MenuItem>
                ) : null}
                {checkedItemCountNumeric > 0 && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            linkCheckedItems(item.record.path)
                        }}
                    >
                        <ButtonPrimitive menuItem>
                            Create {checkedItemsCount} shortcut{checkedItemsCount === '1' ? '' : 's'} here
                        </ButtonPrimitive>
                    </MenuItem>
                ) : null}
                {checkedItemCountNumeric > 0 && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            moveCheckedItems(item.record.path)
                        }}
                    >
                        <ButtonPrimitive menuItem>
                            Move {checkedItemsCount} selected item{checkedItemsCount === '1' ? '' : 's'} here
                        </ButtonPrimitive>
                    </MenuItem>
                ) : null}

                <MenuSeparator />

                {item.record?.path ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            handleCopyPath(item.record?.path)
                        }}
                    >
                        <ButtonPrimitive menuItem>Copy path</ButtonPrimitive>
                    </MenuItem>
                ) : null}
                {item.record?.path && item.record?.shortcut ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            assureVisibility({ type: item.record?.type, ref: item.record?.ref })
                        }}
                    >
                        <ButtonPrimitive menuItem>Show original</ButtonPrimitive>
                    </MenuItem>
                ) : null}
                {item.record?.path && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            rename(item.record as unknown as FileSystemEntry)
                        }}
                    >
                        <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                    </MenuItem>
                ) : null}

                {checkedItemCountNumeric > 1 && checkedItems[item.id] ? (
                    <>
                        <MenuItem asChild>
                            <ButtonPrimitive menuItem disabled>
                                Delete {checkedItemsCount} item{checkedItemCountNumeric === 1 ? '' : 's'}
                            </ButtonPrimitive>
                        </MenuItem>
                        <MenuItem
                            asChild
                            onClick={(e: any) => {
                                e.stopPropagation()
                                deleteCheckedItems()
                            }}
                        >
                            <ButtonPrimitive menuItem>
                                Move {checkedItemsCount} item{checkedItemCountNumeric === 1 ? '' : 's'} to 'Unfiled'
                            </ButtonPrimitive>
                        </MenuItem>
                    </>
                ) : item.record?.shortcut ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            deleteItem(item.record as unknown as FileSystemEntry)
                        }}
                    >
                        <ButtonPrimitive menuItem>Delete shortcut</ButtonPrimitive>
                    </MenuItem>
                ) : (
                    <>
                        <MenuItem asChild disabled>
                            <ButtonPrimitive menuItem disabled={!item.record?.shortcut}>
                                {item.record?.type === 'folder' ? 'Delete folder' : 'Delete'}
                            </ButtonPrimitive>
                        </MenuItem>
                        {item.record?.type === 'folder' || !item.record?.path.startsWith('Unfiled/') ? (
                            <MenuItem
                                asChild
                                onClick={(e: any) => {
                                    e.stopPropagation()
                                    deleteItem(item.record as unknown as FileSystemEntry)
                                }}
                            >
                                <ButtonPrimitive menuItem>
                                    {item.record?.type === 'folder' ? "Move folder to 'Unfiled'" : "Move to 'Unfiled'"}
                                </ButtonPrimitive>
                            </MenuItem>
                        ) : null}
                    </>
                )}

                {item.record?.type === 'folder' || item.id?.startsWith('project-folder-empty/') ? (
                    <>
                        {!item.id?.startsWith('project-folder-empty/') ? <MenuSeparator /> : null}
                        <MenuItem
                            asChild
                            onClick={(e: any) => {
                                e.stopPropagation()
                                createFolder(item.record?.path)
                            }}
                        >
                            <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                        </MenuItem>
                        <MenuSeparator />
                        {treeItemsNew.map((treeItem) => (
                            <MenuItem
                                key={treeItem.id}
                                asChild
                                onClick={(e: any) => {
                                    e.stopPropagation()
                                    const objectType: string | undefined = treeItem.record?.type
                                    const folder = item.record?.path
                                    if (objectType && folder) {
                                        setLastNewOperation(objectType, folder)
                                    }
                                    treeItem.onClick?.()
                                }}
                            >
                                <ButtonPrimitive menuItem>New {treeItem.name}</ButtonPrimitive>
                            </MenuItem>
                        ))}
                    </>
                ) : null}
            </>
        )
    }

    return (
        <PanelLayoutPanel
            searchPlaceholder="Search your project"
            panelActions={
                <>
                    <ButtonPrimitive onClick={() => createFolder('')} tooltip="New root folder">
                        <IconFolderPlus className="text-tertiary" />
                    </ButtonPrimitive>
                    {checkedItemCountNumeric > 0 && checkedItemsCount !== '0+' ? (
                        <ButtonPrimitive onClick={() => setCheckedItems({})} tooltip="Clear">
                            <LemonTag type="highlight">{checkedItemsCount} selected</LemonTag>
                        </ButtonPrimitive>
                    ) : null}
                </>
            }
        >
            <ButtonPrimitive
                tooltip={projectTreeMode === 'tree' ? 'Switch to table view' : 'Switch to tree view'}
                onClick={() => setProjectTreeMode(projectTreeMode === 'tree' ? 'table' : 'tree')}
                className="absolute top-1/2 translate-y-1/2 right-0 translate-x-1/2 z-top w-fit bg-surface-primary border border-primary"
            >
                <IconChevronRight
                    className={cn('size-4', {
                        'rotate-180': projectTreeMode === 'table',
                        'rotate-0': projectTreeMode === 'tree',
                    })}
                />
            </ButtonPrimitive>

            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={treeData}
                mode={projectTreeMode as TreeMode}
                tableViewKeys={getTableViewKeys}
                defaultSelectedFolderOrNodeId={lastViewedId || undefined}
                isItemActive={(item) => {
                    if (!item.record?.href) {
                        return false
                    }
                    return window.location.href.endsWith(item.record?.href)
                }}
                enableMultiSelection={checkedItemCountNumeric > 0}
                onItemChecked={onItemChecked}
                checkedItemCount={checkedItemCountNumeric}
                onNodeClick={(node) => {
                    if (!isLayoutPanelPinned || projectTreeMode === 'table') {
                        clearActivePanelIdentifier()
                        showLayoutPanel(false)
                    }

                    if (node?.record?.path) {
                        setLastViewedId(node?.id || '')
                    }
                    if (node?.id.startsWith('project-load-more/')) {
                        const path = node.id.split('/').slice(1).join('/')
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
                expandedItemIds={searchTerm ? expandedSearchFolders : expandedFolders}
                onSetExpandedItemIds={searchTerm ? setExpandedSearchFolders : setExpandedFolders}
                enableDragAndDrop={true}
                onDragEnd={(dragEvent) => {
                    const itemToId = (item: FileSystemEntry): string =>
                        item.type === 'folder' ? 'project-folder/' + item.path : 'project/' + item.id
                    const oldId = dragEvent.active.id as string
                    const newId = dragEvent.over?.id
                    if (oldId === newId) {
                        return false
                    }
                    const oldItem = viableItems.find((i) => itemToId(i) === oldId)
                    const newItem = viableItems.find((i) => itemToId(i) === newId)
                    if (oldItem === newItem || !oldItem || !newItem) {
                        return false
                    }
                    const oldPath = oldItem.path
                    const folder = newItem.path

                    if (checkedItems[oldId]) {
                        moveCheckedItems(folder)
                    } else if (folder === '') {
                        const oldSplit = splitPath(oldPath)
                        const oldFile = oldSplit.pop()
                        if (oldFile && oldSplit.length > 0) {
                            moveItem(oldItem, joinPath([oldFile]))
                        }
                    } else if (folder) {
                        const oldSplit = splitPath(oldPath)
                        const oldFile = oldSplit.pop()
                        if (oldFile) {
                            const newFile = joinPath([...splitPath(String(folder)), oldFile])
                            if (oldItem && newFile !== oldPath) {
                                moveItem(oldItem, newFile)
                            }
                        }
                    }
                }}
                isItemDraggable={(item) => {
                    return (
                        (item.id.startsWith('project/') || item.id.startsWith('project-folder/')) && item.record?.path
                    )
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
                    return <ContextMenuGroup>{renderMenuItems(item, ContextMenuItem)}</ContextMenuGroup>
                }}
                itemSideAction={(item) => {
                    if (item.id.startsWith('project-folder-empty/')) {
                        return undefined
                    }
                    return <DropdownMenuGroup>{renderMenuItems(item, DropdownMenuItem)}</DropdownMenuGroup>
                }}
                emptySpaceContextMenu={() => {
                    return (
                        <ContextMenuGroup>
                            <ContextMenuItem
                                asChild
                                onClick={(e: any) => {
                                    e.stopPropagation()
                                    createFolder('')
                                }}
                            >
                                <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                            </ContextMenuItem>
                        </ContextMenuGroup>
                    )
                }}
            />
        </PanelLayoutPanel>
    )
}
