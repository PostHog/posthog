import { IconFolderPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { RefObject, useEffect, useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree(): JSX.Element {
    const { treeData, lastViewedId, viableItems, pendingActions } = useValues(projectTreeLogic)

    const {
        createFolder,
        rename,
        deleteItem,
        moveItem,
        toggleFolderOpen,
        setLastViewedId,
        setExpandedFolders,
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
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={cancelPendingActions}
                                tooltip={`Cancel ${pendingActions.length} ${
                                    pendingActions.length === 1 ? 'change' : 'changes'
                                }`}
                                tooltipPlacement="bottom"
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="primary"
                                status="danger"
                                onClick={applyPendingActions}
                                tooltip={`Save ${pendingActions.length} ${
                                    pendingActions.length === 1 ? 'change' : 'changes'
                                }`}
                                tooltipPlacement="bottom"
                            >
                                Save
                            </LemonButton>
                        </div>
                    ) : (
                        <>
                            {/* <LemonButton
                                size="small"
                                type="tertiary"
                                tooltip="Sort by name"
                                onClick={() => alert('Sort by name')}
                                className="shrink-0"
                                icon={
                                    <IconWrapper>
                                        <IconSort />
                                    </IconWrapper>
                                }
                            /> */}
                            <LemonButton
                                size="small"
                                type="tertiary"
                                tooltip="Create new root folder"
                                onClick={() => createFolder('')}
                                className="shrink-0"
                                icon={
                                    <IconWrapper>
                                        <IconFolderPlus />
                                    </IconWrapper>
                                }
                            />
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
                    return window.location.href.includes(item.record?.href) ? true : false
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
                onSetExpandedItemIds={setExpandedFolders}
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
                                onClick={(e) => {
                                    e.stopPropagation()
                                    createFolder(item.record?.path)
                                }}
                            >
                                New Folder
                            </ContextMenuItem>
                            {item.record?.path ? (
                                <ContextMenuItem onClick={() => item.record?.path && rename(item.record.path)}>
                                    Rename
                                </ContextMenuItem>
                            ) : null}
                            {item.record?.path ? (
                                <ContextMenuItem
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        handleCopyPath(item.record?.path)
                                    }}
                                >
                                    Copy Path
                                </ContextMenuItem>
                            ) : null}
                            {item.record?.created_at ? (
                                <ContextMenuItem
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        deleteItem(item.record as unknown as FileSystemEntry)
                                    }}
                                >
                                    Delete
                                </ContextMenuItem>
                            ) : null}
                            {/* Add more menu items as needed */}
                        </ContextMenuGroup>
                    )
                }}
                itemSideAction={(item) => {
                    if (!item.id.startsWith('project/')) {
                        return undefined
                    }
                    return {
                        icon: (
                            <More
                                size="xsmall"
                                onClick={(e) => e.stopPropagation()}
                                overlay={
                                    <>
                                        {item.record?.type === 'folder' || item.record?.type === 'project' ? (
                                            <LemonButton
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    item.record?.path && createFolder(item.record.path)
                                                }}
                                                fullWidth
                                                size="small"
                                            >
                                                New Folder
                                            </LemonButton>
                                        ) : null}
                                        {item.record?.path ? (
                                            <LemonButton
                                                onClick={() => item.record?.path && rename(item.record.path)}
                                                fullWidth
                                                size="small"
                                            >
                                                Rename
                                            </LemonButton>
                                        ) : null}
                                        {item.record?.path ? (
                                            <LemonButton
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    handleCopyPath(item.record?.path)
                                                }}
                                                fullWidth
                                                size="small"
                                            >
                                                Copy Path
                                            </LemonButton>
                                        ) : null}
                                        {item.record?.created_at ? (
                                            <LemonButton
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    deleteItem(item.record as unknown as FileSystemEntry)
                                                }}
                                                fullWidth
                                                size="small"
                                            >
                                                Delete
                                            </LemonButton>
                                        ) : null}
                                    </>
                                }
                            />
                        ),
                        identifier: item.record?.path || 'more',
                    }
                }}
            />
        </PanelLayoutPanel>
    )
}
