import { IconPin, IconPinFilled, IconPlus, IconSearch, IconSort, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { Icon } from 'lib/ui/Icon/Icon'
import { useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { ProjectDropdownMenu } from '../../../panel-layout/ProjectDropdownMenu'
import { navigation3000Logic } from '../../navigationLogic'
import { projectTreeLogic } from './projectTreeLogic'
import { joinPath, splitPath } from './utils'

export function ProjectTree({ contentRef }: { contentRef: React.RefObject<HTMLElement> }): JSX.Element {
    const {
        treeData,
        loadingPaths,
        expandedFolders,
        lastViewedId,
        viableItems,
        pendingActionsCount,
        pendingLoaderLoading,
        searchTerm,
    } = useValues(projectTreeLogic)

    const {
        createFolder,
        rename,
        deleteItem,
        moveItem,
        toggleFolderOpen,
        setLastViewedId,
        setExpandedFolders,
        applyPendingActions,
        cancelPendingActions,
        loadFolder,
        setSearchTerm,
        clearSearch,
    } = useActions(projectTreeLogic)

    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { showLayoutPanel, toggleLayoutPanelPinned } = useActions(panelLayoutLogic)
    const { isLayoutPanelPinned } = useValues(panelLayoutLogic)
    const treeRef = useRef<LemonTreeRef>(null)
    const containerRef = useRef<HTMLDivElement | null>(null)

    const handleCopyPath = (path?: string): void => {
        if (path) {
            void navigator.clipboard.writeText(path)
        }
    }

    return (
        <>
            <nav
                className={clsx('flex flex-col max-h-screen min-h-screen relative w-[320px] border-r border-primary')}
                ref={containerRef}
            >
                <div className="flex justify-between p-1 bg-surface-tertiary">
                    <ProjectDropdownMenu />

                    <div className="flex gap-1 items-center justify-end">
                        <LemonButton
                            size="small"
                            type="tertiary"
                            tooltip="Sort by name"
                            onClick={() => alert('Sort by name')}
                            className="hover:bg-fill-highlight-100 shrink-0"
                            icon={
                                <Icon>
                                    <IconSort />
                                </Icon>
                            }
                        />
                        {!isMobileLayout && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                tooltip={isLayoutPanelPinned ? 'Unpin panel' : 'Pin panel'}
                                onClick={() => toggleLayoutPanelPinned(!isLayoutPanelPinned)}
                                className="hover:bg-fill-highlight-100 shrink-0"
                                icon={
                                    isLayoutPanelPinned ? (
                                        <Icon>
                                            <IconPinFilled />
                                        </Icon>
                                    ) : (
                                        <Icon>
                                            <IconPin />
                                        </Icon>
                                    )
                                }
                            />
                        )}
                        <LemonButton
                            size="small"
                            type="tertiary"
                            tooltip="Create new root folder"
                            onClick={() => createFolder('')}
                            className="hover:bg-fill-highlight-100 shrink-0"
                            icon={
                                <Icon>
                                    <IconPlus />
                                </Icon>
                            }
                        />
                    </div>
                </div>

                <div className="border-b border-secondary h-px" />
                <div className="z-main-nav flex flex-1 flex-col justify-between overflow-y-auto bg-surface-secondary">
                    <div className="flex gap-1 p-1 items-center justify-between">
                        <LemonInput
                            placeholder="Search..."
                            className="w-full"
                            prefix={
                                <Icon>
                                    <IconSearch />
                                </Icon>
                            }
                            size="small"
                            value={searchTerm}
                            onChange={(value) => setSearchTerm(value)}
                            suffix={
                                searchTerm ? (
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        onClick={() => clearSearch()}
                                        icon={
                                            <Icon>
                                                <IconX />
                                            </Icon>
                                        }
                                        className="bg-transparent [&_svg]:opacity-30 hover:[&_svg]:opacity-100"
                                        tooltip="Clear search"
                                    />
                                ) : null
                            }
                            onKeyDown={(e) => {
                                if (e.key === 'ArrowDown') {
                                    e.preventDefault() // Prevent scrolling
                                    const visibleItems = treeRef.current?.getVisibleItems()
                                    if (visibleItems && visibleItems.length > 0) {
                                        e.currentTarget.blur() // Remove focus from input
                                        treeRef.current?.focusItem(visibleItems[0].id)
                                    }
                                }
                            }}
                        />
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
                        </div>
                    </div>

                    <div className="border-b border-primary h-px" />

                    <LemonTree
                        ref={treeRef}
                        contentRef={contentRef}
                        className="px-0 py-1"
                        data={treeData}
                        expandedItemIds={expandedFolders}
                        isFinishedBuildingTreeData={Object.keys(loadingPaths).length === 0}
                        defaultSelectedFolderOrNodeId={lastViewedId || undefined}
                        onNodeClick={(node) => {
                            if (node?.record?.path) {
                                setLastViewedId(node?.id || '')
                                if (!isLayoutPanelPinned) {
                                    showLayoutPanel(false)
                                }
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
                </div>
            </nav>
        </>
    )
}
