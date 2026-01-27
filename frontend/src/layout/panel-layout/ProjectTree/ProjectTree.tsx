import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { RefObject, useCallback, useEffect, useRef, useState } from 'react'

import {
    IconCheckbox,
    IconChevronRight,
    IconEllipsis,
    IconFolderPlus,
    IconGear,
    IconPencil,
    IconPlusSmall,
    IconShortcut,
} from '@posthog/icons'

import { itemSelectModalLogic } from 'lib/components/FileSystem/ItemSelectModal/itemSelectModalLogic'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTree, LemonTreeRef, LemonTreeSize, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { TreeNodeDisplayIcon } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { FileSystemEntry, UserProductListReason } from '~/queries/schema/schema-general'
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

const SHORTCUT_DISMISSAL_LOCAL_STORAGE_KEY = 'shortcut-dismissal'
const CUSTOM_PRODUCT_DISMISSAL_LOCAL_STORAGE_KEY = 'custom-product-dismissal'
const SEEN_CUSTOM_PRODUCTS_LOCAL_STORAGE_KEY = 'seen-custom-products'

const USER_PRODUCT_LIST_REASON_DEFAULTS: { [key in UserProductListReason]?: string } = {
    [UserProductListReason.USED_BY_COLLEAGUES]:
        'We think you might like this product because your colleagues are using it.',
    [UserProductListReason.USED_SIMILAR_PRODUCTS]:
        'We think you might like this product because you use similar products. Give it a try!',
    [UserProductListReason.USED_ON_SEPARATE_TEAM]:
        'You use this product on another project so we think you might like it here.',
    [UserProductListReason.NEW_PRODUCT]: 'This is a brand new product. Give it a try!',
    [UserProductListReason.SALES_LED]: 'This product is recommended for you by our team.',
}

// Show active state for items that are active in the URL
const isItemActive = (item: TreeDataItem): boolean => {
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
        lastViewedId,
        expandedFolders,
        expandedSearchFolders,
        searchTerm,
        searchResults,
        checkedItems,
        checkedItemCountNumeric,
        scrollTargetId,
        editingItemId,
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
        setSelectMode,
        setSearchTerm,
    } = useActions(projectTreeLogic(projectTreeLogicProps))

    const { setPanelTreeRef, resetPanelLayout } = useActions(panelLayoutLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)
    const { currentTeamId } = useValues(teamLogic)
    const treeRef = useRef<LemonTreeRef>(null)
    const { openItemSelectModal } = useActions(itemSelectModalLogic)

    const { customProducts, customProductsLoading } = useValues(customProductsLogic)
    const { seed } = useActions(customProductsLogic)

    const [shortcutHelperDismissed, setShortcutHelperDismissed] = useLocalStorage<boolean>(
        SHORTCUT_DISMISSAL_LOCAL_STORAGE_KEY,
        false
    )
    const [customProductHelperDismissed, setCustomProductHelperDismissed] = useLocalStorage<boolean>(
        CUSTOM_PRODUCT_DISMISSAL_LOCAL_STORAGE_KEY,
        false
    )
    const [seenCustomProducts, setSeenCustomProducts] = useLocalStorage<string[]>(
        `${currentTeamId ?? '*'}-${SEEN_CUSTOM_PRODUCTS_LOCAL_STORAGE_KEY}`,
        []
    )

    const isCustomProductsExperiment = useFeatureFlag('CUSTOM_PRODUCTS_SIDEBAR', 'test')
    const showFilterDropdown = root === 'project://'
    const showSortDropdown = root === 'project://'

    const treeData: TreeDataItem[] = [...fullFileSystemFiltered]
    if (fullFileSystemFiltered.length <= 5) {
        if (root === 'shortcuts://' && (fullFileSystemFiltered.length === 0 || !shortcutHelperDismissed)) {
            treeData.push({
                id: 'products/shortcuts-helper-category',
                name: 'Example shortcuts',
                type: 'category',
                displayName: (
                    <div
                        className={cn('border border-primary text-xs mb-2 font-normal rounded-xs p-2 -mx-1', {
                            'mt-2': fullFileSystemFiltered.length === 0,
                        })}
                    >
                        Shortcuts are added by pressing{' '}
                        <IconEllipsis className="size-3 border border-[var(--color-neutral-500)] rounded-xs" />,
                        side-clicking a panel item, then "Add to shortcuts panel", or inside an app's resources file
                        menu click{' '}
                        <IconShortcut className="size-3 border border-[var(--color-neutral-500)] rounded-xs" />.{' '}
                        {fullFileSystemFiltered.length > 0 && (
                            <span className="cursor-pointer underline" onClick={() => setShortcutHelperDismissed(true)}>
                                Dismiss.
                            </span>
                        )}
                    </div>
                ),
            })
        }

        if (root === 'custom-products://') {
            const hasRecommendedProducts = customProducts.some(
                (item) =>
                    item.reason === UserProductListReason.USED_BY_COLLEAGUES ||
                    item.reason === UserProductListReason.USED_ON_SEPARATE_TEAM
            )

            if (fullFileSystemFiltered.length === 0 || !customProductHelperDismissed) {
                const CustomIcon = isCustomProductsExperiment ? IconGear : IconPencil
                treeData.push({
                    id: 'products/custom-products-helper-category',
                    name: 'Example custom products',
                    type: 'category',
                    displayName: (
                        <div
                            className={cn('border border-primary text-xs mb-2 font-normal rounded-xs p-2 -mx-1', {
                                'mt-6': fullFileSystemFiltered.length === 0,
                            })}
                        >
                            You can display your preferred apps here. You can configure what items show up in here by
                            clicking on the{' '}
                            <CustomIcon className="size-3 border border-[var(--color-neutral-500)] rounded-xs" /> icon
                            above. We'll automatically suggest new apps to this list as you use them.{' '}
                            {fullFileSystemFiltered.length > 0 && (
                                <span
                                    className="cursor-pointer underline"
                                    onClick={() => setCustomProductHelperDismissed(true)}
                                >
                                    Dismiss.
                                </span>
                            )}
                            <br />
                            <br />
                            {!hasRecommendedProducts && fullFileSystemFiltered.length <= 3 && (
                                <span className="cursor-pointer underline" onClick={seed}>
                                    {customProductsLoading ? 'Adding...' : 'Add recommended products?'}
                                </span>
                            )}
                        </div>
                    ),
                })
            }
        }
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

    const handleMouseEnterIndicator = useCallback(
        (itemId: string): void => {
            if (!seenCustomProducts.includes(itemId)) {
                setTimeout(() => setSeenCustomProducts((state) => [...state, itemId]), 250)
            }
        },
        [seenCustomProducts, setSeenCustomProducts]
    )

    const tree = (
        <LemonTree
            ref={treeRef}
            contentRef={mainContentRef as RefObject<HTMLElement>}
            className="px-0 py-1"
            data={treeData}
            mode="tree"
            selectMode={selectMode}
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
                const showDropdownMenu =
                    root === 'products://' ||
                    root === 'custom-products://' ||
                    (root === 'shortcuts://' && item.record?.href && item.record.href.split('/').length - 1 === 1)

                if (showDropdownMenu) {
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
            renderItemTooltip={(item) => {
                const nameNode: JSX.Element = <span className="font-semibold">{item.displayName}</span>

                if (
                    root === 'products://' ||
                    root === 'data://' ||
                    root === 'persons://' ||
                    root === 'custom-products://'
                ) {
                    const key = item.record?.sceneKey
                    const reason = item.record?.reason as UserProductListReason | undefined
                    const reasonText = item.record?.reason_text as string | null | undefined

                    const suggestedProductBaseTooltipText =
                        reasonText || (reason ? USER_PRODUCT_LIST_REASON_DEFAULTS[reason] : undefined)
                    const tooltipText = suggestedProductBaseTooltipText ? (
                        <>
                            {suggestedProductBaseTooltipText}
                            <br />
                            Right-click to remove from sidebar.
                            <br />
                            <br />
                        </>
                    ) : undefined

                    return (
                        <>
                            {tooltipText}
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

                return undefined
            }}
            renderItemIcon={(item) => {
                const createdAt = item.record?.created_at
                const reason = item.record?.reason as UserProductListReason | undefined
                const reasonText = item.record?.reason_text as string | null | undefined
                const itemId = item.id

                // This indicator is shown if we detect we're looking at a custom product
                // that's been recently added to the user's sidebar.
                // We extract the `reasonText` from the item or come up with some default
                // ones for some specific reasons that have a reasonable default.
                // We exclude USED_ON_SEPARATE_TEAM as those are not particularly useful to highlight.
                // We also hide the indicator once the user has hovered over the item.
                const showIndicator =
                    root === 'custom-products://' &&
                    createdAt &&
                    dayjs().diff(dayjs(createdAt), 'days') < 7 &&
                    reason &&
                    reason !== UserProductListReason.USED_ON_SEPARATE_TEAM &&
                    (reasonText || USER_PRODUCT_LIST_REASON_DEFAULTS[reason]) &&
                    !seenCustomProducts.includes(itemId)

                return (
                    <>
                        {sortMethod === 'recent' && item.type !== 'loading-indicator' && (
                            <ProfilePicture
                                user={item.record?.user as UserBasicType | undefined}
                                size="xs"
                                className="ml-[4px]"
                            />
                        )}
                        <div className="relative" onMouseEnter={() => handleMouseEnterIndicator(itemId)}>
                            <TreeNodeDisplayIcon item={item} expandedItemIds={expandedFolders} />
                            {showIndicator && (
                                <div className="absolute top-0.5 -right-0.5 size-2 bg-success rounded-full cursor-pointer animate-pulse-5" />
                            )}
                        </div>
                    </>
                )
            }}
            renderItem={(item) => {
                const isCustomProduct = root === 'custom-products://'
                const isNew =
                    !isCustomProduct &&
                    item.record?.created_at &&
                    dayjs().diff(dayjs(item.record?.created_at), 'minutes') < 3

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

                        {sortMethod === 'recent' && item.type !== 'loading-indicator' && (
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
                {
                    ...(root === 'shortcuts://' &&
                        sortMethod !== 'recent' && {
                            'data-attr': 'shortcuts-panel-add-button',
                            onClick: openItemSelectModal,
                            children: (
                                <>
                                    <IconPlusSmall
                                        className={cn('size-3', {
                                            'text-tertiary': selectMode === 'default',
                                            'text-primary': selectMode === 'multi',
                                        })}
                                    />
                                    Add shortcut
                                </>
                            ),
                        }),
                },
            ]}
        >
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
