import { IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { navigation3000Logic } from '../../navigationLogic'
import { NavbarBottom } from '../NavbarBottom'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree({ contentRef }: { contentRef: React.RefObject<HTMLElement> }): JSX.Element {
    const { theme } = useValues(themeLogic)
    const { isNavShown, mobileLayout } = useValues(navigation3000Logic)
    const { toggleNavCollapsed, hideNavOnMobile } = useActions(navigation3000Logic)
    const {
        treeData,
        loadingPaths,
        expandedFolders,
        lastViewedId,
        viableItems,
        helpNoticeVisible,
        pendingActionsCount,
        pendingLoaderLoading,
    } = useValues(projectTreeLogic)

    const {
        createFolder,
        rename,
        deleteItem,
        moveItem,
        toggleFolderOpen,
        setLastViewedId,
        setExpandedFolders,
        setHelpNoticeVisibility,
        applyPendingActions,
        cancelPendingActions,
        loadFolder,
    } = useActions(projectTreeLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)

    const handleCopyPath = (path?: string): void => {
        if (path) {
            void navigator.clipboard.writeText(path)
        }
    }

    return (
        <>
            <nav className={clsx('Navbar3000', !isNavShown && 'Navbar3000--hidden')} ref={containerRef}>
                <div
                    className="Navbar3000__content w-80"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={theme?.sidebarStyle}
                >
                    <div className="flex gap-1 p-1 items-center justify-between">
                        <h2 className="text-base font-bold m-0 pl-1">Files</h2>
                        <div className="flex gap-1 items-center">
                            {pendingActionsCount > 0 ? (
                                <span>
                                    {pendingActionsCount} <span>{pendingActionsCount > 1 ? 'changes' : 'change'}</span>
                                </span>
                            ) : null}
                            {pendingActionsCount > 0 ? (
                                <LemonButton
                                    onClick={() => {
                                        cancelPendingActions()
                                    }}
                                    type="secondary"
                                    size="small"
                                    tooltip="Click to cancel changes"
                                >
                                    Cancel
                                </LemonButton>
                            ) : null}
                            <LemonButton
                                size="small"
                                type={pendingActionsCount > 0 ? 'primary' : 'secondary'}
                                disabledReason={pendingActionsCount === 0 ? 'Nothing to save' : undefined}
                                className={pendingActionsCount === 0 ? 'opacity-30' : ''}
                                loading={pendingLoaderLoading}
                                tooltip={pendingActionsCount === 0 ? undefined : 'Save recent actions'}
                                onClick={
                                    !pendingLoaderLoading
                                        ? () => {
                                              applyPendingActions()
                                          }
                                        : undefined
                                }
                            >
                                Save
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                tooltip="Create new root folder"
                                onClick={() => createFolder('')}
                                icon={<IconPlusSmall />}
                            />
                        </div>
                    </div>

                    <div className="border-b border-primary h-px" />

                    <LemonTree
                        contentRef={contentRef}
                        className="px-0 py-1"
                        data={treeData}
                        expandedItemIds={expandedFolders}
                        isFinishedBuildingTreeData={Object.keys(loadingPaths).length === 0}
                        defaultSelectedFolderOrNodeId={lastViewedId || undefined}
                        onNodeClick={(node) => {
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
                    {helpNoticeVisible ? (
                        <>
                            <div className="border-b border-primary h-px" />
                            <div className="p-2">
                                <LemonBanner
                                    type="info"
                                    dismissKey="project-tree-help-notice"
                                    onClose={() => setHelpNoticeVisibility(false)}
                                >
                                    <p className="font-semibold mb-1">Behold, 🌲 navigation</p>
                                    <ul className="mb-0 text-xs list-disc pl-4 py-0">
                                        <li>
                                            All your files are still here, open 'unfiled' to see them, and organize them
                                            the way you'd like.
                                        </li>
                                        <li>Right click on tree item for more options.</li>
                                    </ul>
                                </LemonBanner>
                            </div>
                        </>
                    ) : null}
                    <div className="border-b border-primary h-px" />
                    <NavbarBottom />
                </div>
                {!mobileLayout && (
                    <Resizer
                        logicKey="navbar"
                        placement="right"
                        containerRef={containerRef}
                        closeThreshold={100}
                        onToggleClosed={(shouldBeClosed) => toggleNavCollapsed(shouldBeClosed)}
                        onDoubleClick={() => toggleNavCollapsed()}
                    />
                )}
            </nav>
            {mobileLayout && (
                <div
                    className={clsx('Navbar3000__overlay', !isNavShown && 'Navbar3000--hidden')}
                    onClick={() => hideNavOnMobile()}
                />
            )}
        </>
    )
}
