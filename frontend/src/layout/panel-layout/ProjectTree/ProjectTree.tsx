import { IconFolderPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useEffect, useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree(): JSX.Element {
    const { treeData, lastViewedId, viableItems, expandedFolders, expandedSearchFolders, searchTerm, treeItemsNew } =
        useValues(projectTreeLogic)

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

    return (
        <PanelLayoutPanel
            searchPlaceholder="Search your project"
            panelActions={
                <ButtonPrimitive onClick={() => createFolder('')} tooltip="New root folder">
                    <IconFolderPlus className="text-tertiary" />
                </ButtonPrimitive>
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
                onNodeClick={(node) => {
                    if (!isLayoutPanelPinned) {
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
                    return item.id.startsWith('project/') && item.record?.path
                }}
                isItemDroppable={(item) => {
                    const path = item.record?.path || ''

                    // disable dropping for these IDS
                    if (!item.id.startsWith('project/')) {
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
                    if (!item.id.startsWith('project/') && !item.id.startsWith('empty-')) {
                        return undefined
                    }
                    return (
                        <ContextMenuGroup>
                            {item.record?.type === 'folder' ? (
                                <ContextMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        createFolder(item.record?.path)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                                </ContextMenuItem>
                            ) : null}
                            {item.record?.path ? (
                                <ContextMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        item.record?.path && rename(item.record.path)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                                </ContextMenuItem>
                            ) : null}
                            {item.record?.path ? (
                                <ContextMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        handleCopyPath(item.record?.path)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Copy path</ButtonPrimitive>
                                </ContextMenuItem>
                            ) : null}
                            {item.record?.created_at ? (
                                <ContextMenuItem
                                    asChild
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        deleteItem(item.record as unknown as FileSystemEntry)
                                    }}
                                >
                                    <ButtonPrimitive menuItem>Delete</ButtonPrimitive>
                                </ContextMenuItem>
                            ) : null}
                            {item.record?.type === 'folder' || item.id?.startsWith('empty-') ? (
                                <>
                                    {!item.id?.startsWith('empty-') ? <ContextMenuSeparator /> : null}
                                    {treeItemsNew.map((treeItem) => (
                                        <ContextMenuItem
                                            key={treeItem.id}
                                            asChild
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                treeItem.onClick?.()
                                            }}
                                        >
                                            <ButtonPrimitive menuItem>New {treeItem.name}</ButtonPrimitive>
                                        </ContextMenuItem>
                                    ))}
                                </>
                            ) : null}
                        </ContextMenuGroup>
                    )
                }}
                itemSideAction={(item) => {
                    if (!item.id.startsWith('project/') && !item.id.startsWith('empty-')) {
                        return undefined
                    }
                    return (
                        <DropdownMenuGroup>
                            {item.record?.type === 'folder' ? (
                                <DropdownMenuItem
                                    asChild
                                    onClick={() => item.record?.path && createFolder(item.record.path)}
                                >
                                    <ButtonPrimitive menuItem>New folder</ButtonPrimitive>
                                </DropdownMenuItem>
                            ) : null}
                            {item.record?.path ? (
                                <DropdownMenuItem asChild onClick={() => item.record?.path && rename(item.record.path)}>
                                    <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                                </DropdownMenuItem>
                            ) : null}
                            {item.record?.path ? (
                                <DropdownMenuItem asChild onClick={() => handleCopyPath(item.record?.path)}>
                                    <ButtonPrimitive menuItem>Copy path</ButtonPrimitive>
                                </DropdownMenuItem>
                            ) : null}
                            {item.record?.created_at ? (
                                <DropdownMenuItem
                                    asChild
                                    onClick={() => deleteItem(item.record as unknown as FileSystemEntry)}
                                >
                                    <ButtonPrimitive menuItem>Delete</ButtonPrimitive>
                                </DropdownMenuItem>
                            ) : null}
                            {item.record?.type === 'folder' || item.id?.startsWith('empty-') ? (
                                <>
                                    {!item.id?.startsWith('empty-') ? <ContextMenuSeparator /> : null}
                                    {treeItemsNew.map((treeItem) => (
                                        <DropdownMenuItem
                                            key={treeItem.id}
                                            asChild
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                treeItem.onClick?.()
                                            }}
                                        >
                                            <ButtonPrimitive menuItem>New {treeItem.name}</ButtonPrimitive>
                                        </DropdownMenuItem>
                                    ))}
                                </>
                            ) : null}
                        </DropdownMenuGroup>
                    )
                }}
            />
        </PanelLayoutPanel>
    )
}
