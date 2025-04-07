import { IconFolderPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useEffect, useRef } from 'react'

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
        setCheckedItems,
    } = useActions(projectTreeLogic)

    const { showLayoutPanel, setPanelTreeRef, clearActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { mainContentRef, isLayoutPanelPinned } = useValues(panelLayoutLogic)
    const treeRef = useRef<LemonTreeRef>(null)

    const handleCopyPath = (path?: string): void => {
        if (path) {
            void navigator.clipboard.writeText(path)
        }
    }

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
                {checkedItemsCount !== '0' && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            moveCheckedItems(item.record.path)
                        }}
                    >
                        <ButtonPrimitive menuItem>Move {checkedItemsCount} selected items here</ButtonPrimitive>
                    </MenuItem>
                ) : null}
                {checkedItemsCount !== '0' && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            linkCheckedItems(item.record.path)
                        }}
                    >
                        <ButtonPrimitive menuItem>Link {checkedItemsCount} selected items here</ButtonPrimitive>
                    </MenuItem>
                ) : null}
                {item.record?.path && item.record?.type === 'folder' ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            rename(item.record.path)
                        }}
                    >
                        <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                    </MenuItem>
                ) : null}
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
                {item.record?.created_at ? (
                    <MenuItem
                        asChild
                        onClick={(e: any) => {
                            e.stopPropagation()
                            deleteItem(item.record as unknown as FileSystemEntry)
                        }}
                    >
                        <ButtonPrimitive menuItem>Delete and move to 'Unfiled'</ButtonPrimitive>
                    </MenuItem>
                ) : null}
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
                        {treeItemsNew.map((treeItem: any) => (
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
                    {checkedItemsCount !== '0' && checkedItemsCount !== '0+' ? (
                        <ButtonPrimitive onClick={() => setCheckedItems({})} tooltip="Clear">
                            <LemonTag type="highlight">{checkedItemsCount} selected</LemonTag>
                        </ButtonPrimitive>
                    ) : null}
                </>
            }
        >
            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={treeData}
                defaultSelectedFolderOrNodeId={lastViewedId || undefined}
                isItemActive={(item) => {
                    if (!item.record?.href) {
                        return false
                    }
                    return window.location.href.endsWith(item.record?.href)
                }}
                enableMultiSelection={checkedItemsCount !== '0'}
                onItemChecked={onItemChecked}
                onNodeClick={(node) => {
                    if (!isLayoutPanelPinned) {
                        clearActivePanelIdentifier()
                        showLayoutPanel(false)
                    }

                    if (node?.record?.path) {
                        setLastViewedId(node?.id || '')
                    }
                    if (node?.id.startsWith('folder-load-more/')) {
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
                    const oldPath = dragEvent.active.id as string
                    const folder = dragEvent.over?.id

                    if (oldPath === folder) {
                        return false
                    }

                    if (folder === '') {
                        const oldSplit = splitPath(oldPath)
                        const oldFile = oldSplit.pop()
                        if (oldFile && oldSplit.length > 0) {
                            moveItem(oldPath, joinPath([oldFile]))
                        }
                    } else if (folder) {
                        const item = viableItems.find((i) => i.path === folder)
                        if (!item || item.type === 'folder') {
                            const oldSplit = splitPath(oldPath)
                            const oldFile = oldSplit.pop()
                            if (oldFile) {
                                const newFile = joinPath([...splitPath(String(folder)), oldFile])
                                if (newFile !== oldPath) {
                                    moveItem(oldPath, newFile)
                                }
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
            />
        </PanelLayoutPanel>
    )
}
