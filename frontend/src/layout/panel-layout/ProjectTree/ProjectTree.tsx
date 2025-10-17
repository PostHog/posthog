import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, useEffect, useRef, useState } from 'react'

import {
    IconCheckbox,
    IconChevronRight,
    IconEllipsis,
    IconFolderPlus,
    IconPlusSmall,
    IconShortcut,
} from '@posthog/icons'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { dayjs } from 'lib/dayjs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, LemonTreeSize, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneConfigurations } from 'scenes/scenes'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { UserBasicType } from '~/types'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { TreeFiltersDropdownMenu } from './TreeFiltersDropdownMenu'
import { TreeSearchField } from './TreeSearchField'
import { TreeSortDropdownMenu } from './TreeSortDropdownMenu'
import { MenuItems } from './menus/MenuItems'
import { projectTreeLogic } from './projectTreeLogic'
import { calculateMovePath } from './utils'

export interface ProjectTreeProps {
    logicKey?: string // key override?
    root?: string
    onlyTree?: boolean
    showRecents?: boolean // whether to show recents in the tree
    searchPlaceholder?: string
    treeSize?: LemonTreeSize
}

export const PROJECT_TREE_KEY = 'project-tree'
let counter = 0

export function ProjectTree({
    logicKey,
    root,
    onlyTree = false,
    searchPlaceholder,
    treeSize = 'default',
    showRecents,
}: ProjectTreeProps): JSX.Element {
    const [uniqueKey] = useState(() => `project-tree-${counter++}`)
    const { viableItems } = useValues(projectTreeDataLogic)
    const projectTreeLogicProps = { key: logicKey ?? uniqueKey, root }
    const {
        fullFileSystemFiltered,
        treeTableKeys,
        lastViewedId,
        expandedFolders,
        expandedSearchFolders,
        searchTerm,
        searchResults,
        checkedItems,
        checkedItemCountNumeric,
        scrollTargetId,
        editingItemId,
        treeTableColumnSizes,
        treeTableTotalWidth,
        sortMethod: projectSortMethod,
        selectMode,
        sortMethod,
    } = useValues(projectTreeLogic(projectTreeLogicProps))
    const {
        createFolder,
        rename,
        moveItem,
        toggleFolderOpen,
        setLastViewedId,
        setExpandedFolders,
        setExpandedSearchFolders,
        loadFolder,
        onItemChecked,
        moveCheckedItems,
        clearScrollTarget,
        setEditingItemId,
        setSortMethod,
        setTreeTableColumnSizes,
        setSelectMode,
        setSearchTerm,
    } = useActions(projectTreeLogic(projectTreeLogicProps))

    const { setPanelTreeRef, resetPanelLayout } = useActions(panelLayoutLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)
    const treeRef = useRef<LemonTreeRef>(null)
    const { projectTreeMode } = useValues(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { setProjectTreeMode } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))

    const showFilterDropdown = root === 'project://'
    const showSortDropdown = root === 'project://'

    const treeData: TreeDataItem[] = []
    if (root === 'shortcuts://' && fullFileSystemFiltered.length === 0) {
        treeData.push({
            id: 'products/shortcuts-helper-category',
            name: 'Example shortcuts',
            type: 'category',
            displayName: (
                <div className="border border-primary text-xs mb-2 font-normal rounded-xs p-1 -mx-1">
                    Shortcuts are added by pressing{' '}
                    <IconEllipsis className="size-3 border border-[var(--color-neutral-500)] rounded-xs" />,
                    side-clicking a panel item, then "Add to shortcuts panel", or inside an app's resources file menu
                    click <IconShortcut className="size-3 border border-[var(--color-neutral-500)] rounded-xs" />
                </div>
            ),
        })
    } else {
        treeData.push(...fullFileSystemFiltered)
    }

    useEffect(() => {
        setPanelTreeRef(treeRef)
    }, [treeRef, setPanelTreeRef])

    useEffect(() => {
        if (projectSortMethod !== (sortMethod ?? 'folder')) {
            setSortMethod(sortMethod ?? 'folder')
        }
    }, [sortMethod, projectSortMethod, setSortMethod])

    // When logic requests a scroll, focus the item and clear the request
    useEffect(() => {
        if (scrollTargetId && treeRef.current) {
            treeRef.current.focusItem(scrollTargetId)
            setLastViewedId(scrollTargetId) // keeps selection in sync
            clearScrollTarget()
        }
    }, [scrollTargetId, treeRef, clearScrollTarget, setLastViewedId])

    // Show active state for items that are active in the URL
    function isItemActive(item: TreeDataItem): boolean {
        if (!item.record?.href) {
            return false
        }

        const currentPath = removeProjectIdIfPresent(window.location.pathname)
        const itemHref = typeof item.record.href === 'string' ? item.record.href : ''

        if (currentPath === itemHref) {
            return true
        }

        // Current path is a sub-path of item (e.g., /insights/new under /insights)
        if (currentPath.startsWith(itemHref + '/')) {
            return true
        }

        // Special handling for products with child pages on distinct paths (e.g., /replay/home and /replay/playlists)
        if (item.name === 'Session replay' && currentPath.startsWith('/replay/')) {
            return true
        }
        if (item.name === 'Data pipelines' && currentPath.startsWith('/pipeline/')) {
            return true
        }
        if (item.name === 'Workflows' && currentPath.startsWith('/workflows')) {
            return true
        }

        return false
    }

    const tree = (
        <LemonTree
            ref={treeRef}
            contentRef={mainContentRef as RefObject<HTMLElement>}
            className="px-0 py-1"
            data={treeData}
            mode={onlyTree ? 'tree' : projectTreeMode}
            selectMode={selectMode}
            tableViewKeys={treeTableKeys}
            defaultSelectedFolderOrNodeId={lastViewedId || undefined}
            isItemActive={isItemActive}
            size={treeSize}
            onItemChecked={onItemChecked}
            checkedItemCount={checkedItemCountNumeric}
            disableScroll={onlyTree ? true : false}
            onItemClick={(item, event) => {
                event.preventDefault()
                if (item?.type === 'empty-folder' || item?.type === 'loading-indicator') {
                    return
                }
                if (item?.record?.href) {
                    router.actions.push(
                        typeof item.record.href === 'function' ? item.record.href(item.record.ref) : item.record.href
                    )
                }

                if (item?.record?.path) {
                    setLastViewedId(item?.id || '')
                }
                if (item?.id.startsWith('project://-load-more/')) {
                    const path = item.id.substring('project://-load-more/'.length)
                    if (path) {
                        loadFolder(path)
                    }
                }

                // False, because we handle focus of content in LemonTree with mainContentRef prop
                resetPanelLayout(false)
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
                    item.type === 'folder' ? 'project://' + item.path : 'project/' + item.id
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
                    : newId && String(newId).startsWith('project://')
                      ? String(newId).substring(10)
                      : ''

                if (checkedItems[oldId]) {
                    moveCheckedItems(folder)
                } else {
                    const { newPath, isValidMove } = calculateMovePath(oldItem, folder)
                    if (isValidMove) {
                        moveItem(oldItem, newPath, false, logicKey ?? uniqueKey)
                    }
                }
            }}
            isItemDraggable={(item) => {
                return (item.id.startsWith('project/') || item.id.startsWith('project://')) && item.record?.path
            }}
            isItemDroppable={(item) => {
                const path = item.record?.path || ''

                // disable dropping for these IDS
                if (!item.id.startsWith('project://')) {
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

                return (
                    <ContextMenuGroup className="group/colorful-product-icons colorful-product-icons-true">
                        <MenuItems item={item} type="context" root={root} onlyTree={onlyTree} logicKey={logicKey} />
                    </ContextMenuGroup>
                )
            }}
            itemSideAction={(item) => {
                if (item.id.startsWith('project-folder-empty/')) {
                    return undefined
                }

                return (
                    <DropdownMenuGroup className="group/colorful-product-icons colorful-product-icons-true">
                        <MenuItems item={item} type="dropdown" root={root} onlyTree={onlyTree} logicKey={logicKey} />
                    </DropdownMenuGroup>
                )
            }}
            itemSideActionButton={(item) => {
                const showProductMenuItems =
                    root === 'products://' ||
                    (root === 'shortcuts://' && item.record?.href && item.record.href.split('/').length - 1 === 1)

                if (showProductMenuItems) {
                    if (item.name === 'Product analytics') {
                        return (
                            <ButtonPrimitive iconOnly isSideActionRight className="z-2">
                                <IconPlusSmall className="text-tertiary" />
                            </ButtonPrimitive>
                        )
                    } else if (item.name === 'Dashboards' || item.name === 'Session replay') {
                        return (
                            <ButtonPrimitive iconOnly isSideActionRight className="z-2">
                                <IconChevronRight className="size-3 text-tertiary rotate-90" />
                            </ButtonPrimitive>
                        )
                    }
                }
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
                            const value = header.key.split('.').reduce((obj, key) => obj?.[key], item)
                            const isFolder =
                                (item.children && item.children.length > 0) || item.record?.type === 'folder'
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
                                        <span
                                            className={cn(
                                                'starting:opacity-0 opacity-100 delay-50 motion-safe:transition-opacity duration-100 font-normal truncate',
                                                {
                                                    'font-semibold':
                                                        index === 0 && isFolder && item.type !== 'empty-folder',
                                                }
                                            )}
                                        >
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
                const nameNode: JSX.Element = <span className="font-semibold">{item.displayName}</span>

                if (root === 'products://' || root === 'data://' || root === 'persons://') {
                    let key = item.record?.sceneKey
                    return (
                        <>
                            {sceneConfigurations[key]?.description || item.name}

                            {item.tags?.length && (
                                <>
                                    {item.tags?.map((tag) => (
                                        <LemonTag
                                            key={tag}
                                            type={
                                                tag === 'alpha' ? 'completion' : tag === 'beta' ? 'warning' : 'success'
                                            }
                                            size="small"
                                            className="ml-2 relative top-[-1px]"
                                        >
                                            {tag.toUpperCase()}
                                        </LemonTag>
                                    ))}
                                </>
                            )}
                        </>
                    )
                }
                if (root === 'persons://') {
                    return (
                        <>
                            {nameNode}
                            {item.record?.protocol === 'products://' && item.tags?.length && (
                                <>
                                    {item.tags?.map((tag) => (
                                        <LemonTag
                                            key={tag}
                                            type={
                                                tag === 'alpha' ? 'completion' : tag === 'beta' ? 'warning' : 'success'
                                            }
                                            size="small"
                                            className="ml-2 relative top-[-1px]"
                                        >
                                            {tag.toUpperCase()}
                                        </LemonTag>
                                    ))}
                                </>
                            )}
                        </>
                    )
                }
                if (root === 'new://') {
                    if (item.children) {
                        return <>View all</>
                    }
                    return <>Create a new {nameNode}</>
                }
                return projectTreeMode === 'tree' ? (
                    <>
                        Name: {nameNode} <br />
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
                        <TreeNodeDisplayIcon item={item} expandedItemIds={expandedFolders} />
                    </>
                )
            }}
            renderItem={(item) => {
                const isNew = item.record?.created_at && dayjs().diff(dayjs(item.record?.created_at), 'minutes') < 3

                return (
                    <span className="truncate">
                        <span
                            className={cn('truncate', {
                                'font-semibold': item.record?.type === 'folder' && item.type !== 'empty-folder',
                            })}
                        >
                            {item.displayName}{' '}
                            {isNew ? (
                                <LemonTag type="highlight" size="small" className="ml-1 relative top-[-1px]">
                                    New
                                </LemonTag>
                            ) : null}
                        </span>

                        {sortMethod === 'recent' && projectTreeMode === 'tree' && item.type !== 'loading-indicator' && (
                            <span className="text-tertiary text-xxs pt-[3px] ml-1">
                                {dayjs(item.record?.created_at).fromNow()}
                            </span>
                        )}

                        {item.tags?.length && (
                            <>
                                {item.tags?.map((tag) => (
                                    <LemonTag
                                        key={tag}
                                        type={tag === 'alpha' ? 'completion' : tag === 'beta' ? 'warning' : 'success'}
                                        size="small"
                                        className="ml-2 relative top-[-1px]"
                                    >
                                        {tag.toUpperCase()}
                                    </LemonTag>
                                ))}
                            </>
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
            searchField={
                <BindLogic logic={projectTreeLogic} props={projectTreeLogicProps}>
                    <TreeSearchField root={root} placeholder={searchPlaceholder} />
                </BindLogic>
            }
            filterDropdown={
                showFilterDropdown ? (
                    <TreeFiltersDropdownMenu setSearchTerm={setSearchTerm} searchTerm={searchTerm} />
                ) : null
            }
            sortDropdown={
                showSortDropdown ? <TreeSortDropdownMenu sortMethod={sortMethod} setSortMethod={setSortMethod} /> : null
            }
            panelActionsNewSceneLayout={[
                {
                    ...(root === 'project://' &&
                        sortMethod !== 'recent' && {
                            tooltip: 'New root folder',
                            'data-attr': 'tree-panel-new-root-folder-button',
                            onClick: () => createFolder(''),
                            children: (
                                <>
                                    <IconFolderPlus className="text-tertiary size-3" />
                                    New root folder
                                </>
                            ),
                        }),
                },
                {
                    ...(root === 'project://' &&
                        sortMethod !== 'recent' && {
                            tooltip: selectMode === 'default' ? 'Enable multi-select' : 'Disable multi-select',
                            'data-attr': 'tree-panel-enable-multi-select-button',
                            onClick: () => setSelectMode(selectMode === 'default' ? 'multi' : 'default'),
                            active: selectMode === 'multi',
                            'aria-pressed': selectMode === 'multi',
                            children: (
                                <>
                                    <IconCheckbox
                                        className={cn('size-3', {
                                            'text-tertiary': selectMode === 'default',
                                            'text-primary': selectMode === 'multi',
                                        })}
                                    />
                                    {selectMode === 'default' ? 'Enable multi-select' : 'Disable multi-select'}
                                </>
                            ),
                        }),
                },
            ]}
        >
            {root === 'project://' && (
                <ButtonPrimitive
                    tooltip={projectTreeMode === 'tree' ? 'Switch to table view' : 'Switch to tree view'}
                    onClick={() => setProjectTreeMode(projectTreeMode === 'tree' ? 'table' : 'tree')}
                    className="absolute top-1/2 translate-y-1/2 right-0 translate-x-1/2  bg-surface-primary border border-primary z-[var(--z-resizer)]"
                    data-attr="tree-panel-switch-view-button"
                    iconOnly
                >
                    <IconChevronRight
                        className={cn('size-3', {
                            'rotate-180': projectTreeMode === 'table',
                            'rotate-0': projectTreeMode === 'tree',
                        })}
                    />
                </ButtonPrimitive>
            )}
            {showRecents && (
                <>
                    <div role="status" aria-live="polite" className="sr-only">
                        Sorted {sortMethod === 'recent' ? 'by creation date' : 'alphabetically'}
                    </div>
                </>
            )}

            {tree}
        </PanelLayoutPanel>
    )
}
