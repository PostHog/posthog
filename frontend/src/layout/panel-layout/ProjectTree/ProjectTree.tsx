import { IconFolderPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { Button } from 'lib/ui/Button/Button'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useEffect, useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree(): JSX.Element {
    const { treeData, lastViewedId, viableItems, pendingActions, expandedFolders, expandedSearchFolders, searchTerm } =
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
        applyPendingActions,
        cancelPendingActions,
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
                <>
                    {pendingActions.length > 0 ? (
                        <div className="flex gap-1">
                            <Button.Root onClick={cancelPendingActions} size="sm" intent="outline">
                                <Button.Label size="sm">Cancel</Button.Label>
                            </Button.Root>
                            <Button.Root onClick={applyPendingActions} size="sm" intent="outline">
                                <Button.Label size="sm">Save</Button.Label>
                            </Button.Root>
                        </div>
                    ) : (
                        <>
                            <Button.Root onClick={() => createFolder('')}>
                                <Button.Icon>
                                    <IconFolderPlus className="text-tertiary" />
                                </Button.Icon>
                            </Button.Root>
                        </>
                    )}
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
                    if (!item.id.startsWith('project/')) {
                        return undefined
                    }
                    return (
                        <ContextMenuGroup>
                            <ContextMenuItem
                                asChild
                                onClick={(e) => {
                                    e.stopPropagation()
                                    createFolder(item.record?.path)
                                }}
                            >
                                <Button.Root size="sm" menuItem>
                                    <Button.Label>New folder</Button.Label>
                                </Button.Root>
                            </ContextMenuItem>
                            {item.record?.path ? (
                                <ContextMenuItem asChild onClick={() => item.record?.path && rename(item.record.path)}>
                                    <Button.Root size="sm" menuItem>
                                        <Button.Label>Rename</Button.Label>
                                    </Button.Root>
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
                                    <Button.Root size="sm" menuItem>
                                        <Button.Label>Copy path</Button.Label>
                                    </Button.Root>
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
                                    <Button.Root size="sm" menuItem>
                                        <Button.Label>Delete</Button.Label>
                                    </Button.Root>
                                </ContextMenuItem>
                            ) : null}
                        </ContextMenuGroup>
                    )
                }}
                itemSideAction={(item) => {
                    if (!item.id.startsWith('project/')) {
                        return undefined
                    }
                    return (
                        <DropdownMenuGroup>
                            <DropdownMenuItem
                                asChild
                                onClick={() => item.record?.path && createFolder(item.record.path)}
                            >
                                <Button.Root size="sm" menuItem>
                                    <Button.Label>New folder</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild onClick={() => item.record?.path && rename(item.record.path)}>
                                <Button.Root size="sm" menuItem>
                                    <Button.Label>Rename</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild onClick={() => handleCopyPath(item.record?.path)}>
                                <Button.Root size="sm" menuItem>
                                    <Button.Label>Copy path</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                asChild
                                onClick={() => deleteItem(item.record as unknown as FileSystemEntry)}
                            >
                                <Button.Root size="sm" menuItem>
                                    <Button.Label>Delete</Button.Label>
                                </Button.Root>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    )
                }}
            />
        </PanelLayoutPanel>
    )
}
