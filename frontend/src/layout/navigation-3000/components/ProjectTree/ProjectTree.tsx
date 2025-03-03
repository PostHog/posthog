import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'
import { useRef } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { navigation3000Logic } from '../../navigationLogic'
import { KeyboardShortcut } from '../KeyboardShortcut'
import { NavbarBottom } from '../NavbarBottom'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree({ contentRef }: { contentRef: React.RefObject<HTMLElement> }): JSX.Element {
    const { theme } = useValues(themeLogic)
    const { isNavShown, mobileLayout } = useValues(navigation3000Logic)
    const { toggleNavCollapsed, hideNavOnMobile } = useActions(navigation3000Logic)
    const { treeData, loadingPaths, expandedFolders, lastViewedPath, viableItems, helpNoticeVisible } =
        useValues(projectTreeLogic)

    const {
        addFolder,
        deleteItem,
        moveItem,
        loadFolder,
        toggleFolder,
        updateSelectedFolder,
        updateLastViewedPath,
        updateExpandedFolders,
        updateHelpNoticeVisibility,
    } = useActions(projectTreeLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)

    // Items that should not be draggable or droppable, or have a side action
    // TODO: sync with projectTreeLogic
    const specialItemsIds: string[] = [
        'project',
        'project/Explore',
        'project/Create new',
        '__separator__',
        '__apply_pending_actions__',
    ]

    return (
        <>
            <nav className={clsx('Navbar3000', !isNavShown && 'Navbar3000--hidden')} ref={containerRef}>
                <div
                    className="Navbar3000__content w-80"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={theme?.sidebarStyle}
                >
                    <LemonTree
                        contentRef={contentRef}
                        className="px-0 py-1"
                        data={treeData}
                        expandedItemIds={expandedFolders}
                        isFinishedBuildingTreeData={Object.keys(loadingPaths).length === 0}
                        defaultSelectedFolderOrNodeId={lastViewedPath || undefined}
                        onNodeClick={(node) => {
                            if (node?.record?.type === 'project' || node?.record?.type === 'folder') {
                                updateLastViewedPath(node.record?.path)
                            }
                        }}
                        onFolderClick={(folder, isExpanded) => {
                            if (folder) {
                                updateSelectedFolder(folder.record?.path || '')
                                toggleFolder(folder.record?.path || '', isExpanded)
                                if (isExpanded && folder.record?.id) {
                                    loadFolder(folder.record?.path || '')
                                }
                            }
                        }}
                        onSetExpandedItemIds={updateExpandedFolders}
                        enableDragAndDrop={true}
                        onDragEnd={(dragEvent) => {
                            const oldPath = dragEvent.active.id as string
                            const folder = dragEvent.over?.id

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
                                item.record?.type !== 'project' &&
                                item.record?.path &&
                                !specialItemsIds.includes(item.id || '')
                            )
                        }}
                        isItemDroppable={(item) => {
                            const path = item.record?.path || ''

                            // disable dropping for special items
                            if (specialItemsIds.includes(item.id || '')) {
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
                        itemSideAction={(item) => {
                            if (specialItemsIds.includes(item.id || '')) {
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
                                                            const folder = prompt(
                                                                item.record?.path
                                                                    ? `Create a folder under "${item.record?.path}":`
                                                                    : 'Create a new folder:',
                                                                ''
                                                            )
                                                            if (folder) {
                                                                addFolder(
                                                                    item.record?.path
                                                                        ? joinPath([
                                                                              ...splitPath(item.record?.path ?? ''),
                                                                              folder,
                                                                          ])
                                                                        : folder
                                                                )
                                                            }
                                                        }}
                                                        fullWidth
                                                        size="small"
                                                    >
                                                        New Folder
                                                    </LemonButton>
                                                ) : null}
                                                {item.record?.path ? (
                                                    <LemonButton
                                                        onClick={() => {
                                                            const oldPath = item.record?.path
                                                            const splits = splitPath(oldPath)
                                                            if (splits.length > 0) {
                                                                const folder = prompt(
                                                                    'New name?',
                                                                    splits[splits.length - 1]
                                                                )
                                                                if (folder) {
                                                                    moveItem(
                                                                        oldPath,
                                                                        joinPath([...splits.slice(0, -1), folder])
                                                                    )
                                                                }
                                                            }
                                                        }}
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
                                                            if (item.record?.path) {
                                                                void navigator.clipboard.writeText(item.record?.path)
                                                            }
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
                                    onClose={() => updateHelpNoticeVisibility(false)}
                                >
                                    <p className="font-semibold mb-1">Behold, 🌲 navigation</p>
                                    <ul className="mb-0 text-xs list-disc pl-4 py-0">
                                        <li>
                                            All your files are still here, open 'unfiled' to see them, and organize them
                                            the way you'd like.
                                        </li>
                                        <li>
                                            Hold down <KeyboardShortcut command /> to enable drag and drop.
                                        </li>
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
