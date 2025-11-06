import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { linkToLogic } from 'lib/components/FileSystem/LinkTo/linkToLogic'
import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { openDeleteGroupTypeDialog } from 'scenes/settings/environment/GroupAnalyticsConfig'
import { groupAnalyticsConfigLogic } from 'scenes/settings/environment/groupAnalyticsConfigLogic'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import { NewMenu } from '../../menus/NewMenu'
import { panelLayoutLogic } from '../../panelLayoutLogic'
import { projectTreeDataLogic } from '../projectTreeDataLogic'
import { projectTreeLogic } from '../projectTreeLogic'
import { joinPath, splitPath } from '../utils'
import { AddShortcutMenuItem } from './AddShortcutMenuItem'
import { BrowserLikeMenuItems } from './BrowserLikeMenuItems'
import { DashboardsMenuItems } from './DashboardsMenuItems'
import { ProductAnalyticsMenuItems } from './ProductAnalyticsMenuItems'
import { SessionReplayMenuItems } from './SessionReplayMenuItems'

interface MenuItemsProps {
    item: TreeDataItem
    type: 'context' | 'dropdown'
    root?: string
    onlyTree?: boolean
    logicKey?: string
    showSelectMenuOption?: boolean
}

let counter = 0

export function MenuItems({
    item,
    type,
    root,
    onlyTree,
    logicKey,
    showSelectMenuOption = true,
}: MenuItemsProps): JSX.Element {
    const [uniqueKey] = useState(() => `project-tree-${counter++}`)
    const { shortcutNonFolderPaths } = useValues(projectTreeDataLogic)
    const { deleteShortcut, addShortcutItem } = useActions(projectTreeDataLogic)
    const { groupTypes } = useValues(groupAnalyticsConfigLogic)
    const { deleteGroupType } = useActions(groupAnalyticsConfigLogic)
    const projectTreeLogicProps = { key: logicKey ?? uniqueKey, root }
    const { checkedItems, checkedItemsCount, checkedItemCountNumeric, checkedItemsArray } = useValues(
        projectTreeLogic(projectTreeLogicProps)
    )
    const {
        createFolder,
        deleteItem,
        onItemChecked,
        moveCheckedItems,
        linkCheckedItems,
        assureVisibility,
        setEditingItemId,
    } = useActions(projectTreeLogic(projectTreeLogicProps))
    const { openMoveToModal } = useActions(moveToLogic)
    const { openLinkToModal } = useActions(linkToLogic)

    const { resetPanelLayout } = useActions(panelLayoutLogic)

    const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem
    const MenuSeparator = type === 'context' ? ContextMenuSeparator : DropdownMenuSeparator
    const MenuSub = type === 'context' ? ContextMenuSub : DropdownMenuSub
    const MenuSubTrigger = type === 'context' ? ContextMenuSubTrigger : DropdownMenuSubTrigger
    const MenuSubContent = type === 'context' ? ContextMenuSubContent : DropdownMenuSubContent
    const MenuGroup = type === 'context' ? ContextMenuGroup : DropdownMenuGroup

    const showSelectMenuItems =
        root === 'project://' && item.record?.path && !item.disableSelect && !onlyTree && showSelectMenuOption

    // Show product menu items if the item is a product or shortcut (and the item is a product, products have 1 slash in the href)
    const showProductMenuItems =
        root === 'products://' ||
        (root === 'shortcuts://' && item.record?.href && item.record.href.split('/').length - 1 === 1)

    // Note: renderMenuItems() is called often, so we're using custom components to isolate logic and network requests
    const productMenu =
        showProductMenuItems && item.name === 'Product analytics' ? (
            <>
                <ProductAnalyticsMenuItems
                    MenuItem={MenuItem}
                    MenuGroup={MenuGroup}
                    MenuSeparator={MenuSeparator}
                    onLinkClick={(keyboardAction) => resetPanelLayout(keyboardAction ?? false)}
                />
                <MenuSeparator />
            </>
        ) : showProductMenuItems && item.name === 'Session replay' ? (
            <>
                <SessionReplayMenuItems
                    MenuItem={MenuItem}
                    MenuGroup={MenuGroup}
                    MenuSub={MenuSub}
                    MenuSubTrigger={MenuSubTrigger}
                    MenuSubContent={MenuSubContent}
                    MenuSeparator={MenuSeparator}
                    onLinkClick={(keyboardAction) => resetPanelLayout(keyboardAction ?? false)}
                />
                <MenuSeparator />
            </>
        ) : showProductMenuItems && item.name === 'Dashboards' ? (
            <>
                <DashboardsMenuItems
                    MenuItem={MenuItem}
                    MenuSub={MenuSub}
                    MenuSubTrigger={MenuSubTrigger}
                    MenuSubContent={MenuSubContent}
                    MenuSeparator={MenuSeparator}
                    MenuGroup={MenuGroup}
                    onLinkClick={(keyboardAction) => resetPanelLayout(keyboardAction ?? false)}
                />
                <MenuSeparator />
            </>
        ) : null

    const isItemAFolder = item.record?.type === 'folder'
    const itemShortcutPath = joinPath([splitPath(item.record?.path).pop() ?? 'Unnamed'])
    const isItemAlreadyInShortcut = !isItemAFolder && shortcutNonFolderPaths.has(itemShortcutPath)
    return (
        <>
            {productMenu}
            {showSelectMenuItems ? (
                <>
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            onItemChecked(item.id, !checkedItems[item.id], false)
                        }}
                        data-attr="tree-item-menu-select-button"
                    >
                        <ButtonPrimitive menuItem>{checkedItems[item.id] ? 'Deselect' : 'Select'}</ButtonPrimitive>
                    </MenuItem>
                    <MenuSeparator />
                </>
            ) : null}

            {item.record?.path && item.record?.type !== 'folder' && item.record?.href ? (
                <>
                    <BrowserLikeMenuItems
                        href={item.record?.href}
                        MenuItem={MenuItem}
                        resetPanelLayout={resetPanelLayout}
                    />
                    <MenuSeparator />
                </>
            ) : null}

            {checkedItemCountNumeric > 0 && item.record?.type === 'folder' ? (
                <>
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            moveCheckedItems(item?.record?.path)
                        }}
                        data-attr="tree-item-menu-move-checked-items-button"
                    >
                        <ButtonPrimitive menuItem>
                            Move {checkedItemsCount} selected item{checkedItemsCount === '1' ? '' : 's'} here
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            linkCheckedItems(item?.record?.path)
                        }}
                        data-attr="tree-item-menu-create-shortcut-button"
                    >
                        <ButtonPrimitive menuItem>
                            Create {checkedItemsCount} shortcut{checkedItemsCount === '1' ? '' : 's'} here
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuSeparator />
                </>
            ) : null}

            {(item.record?.protocol === 'project://' && item.record?.type === 'folder') ||
            item.id?.startsWith('project-folder-empty/') ? (
                <>
                    <MenuSub key="new">
                        <MenuSubTrigger asChild data-attr="tree-item-menu-open-new-menu-button">
                            <ButtonPrimitive
                                menuItem
                                onClick={(e) => {
                                    e.stopPropagation()
                                }}
                            >
                                New...
                                <IconChevronRight className="ml-auto size-3" />
                            </ButtonPrimitive>
                        </MenuSubTrigger>
                        <MenuSubContent>
                            <NewMenu type={type} item={item} createFolder={createFolder} />
                        </MenuSubContent>
                    </MenuSub>
                    <MenuSeparator />
                </>
            ) : null}
            {item.record?.path ? (
                root === 'shortcuts://' ? (
                    item.id.startsWith('shortcuts://') || item.id.startsWith('shortcuts/') ? (
                        <MenuItem
                            asChild
                            onClick={(e) => {
                                e.stopPropagation()
                                item.record && deleteShortcut(item.record?.id)
                            }}
                            data-attr="tree-item-menu-remove-from-shortcuts-button"
                        >
                            <ButtonPrimitive menuItem>Remove from shortcuts</ButtonPrimitive>
                        </MenuItem>
                    ) : null
                ) : isItemAlreadyInShortcut ? (
                    <MenuItem asChild disabled={true} data-attr="tree-item-menu-add-to-shortcuts-disabled-button">
                        <ButtonPrimitive menuItem disabled={true}>
                            Already in shortcuts panel
                        </ButtonPrimitive>
                    </MenuItem>
                ) : (
                    <AddShortcutMenuItem
                        MenuItem={MenuItem}
                        onClick={() => {
                            item.record && addShortcutItem(item.record as FileSystemEntry)
                        }}
                        dataAttr="tree-item-menu-add-to-shortcuts-button"
                    />
                )
            ) : null}

            {item.id.startsWith('project/') || item.id.startsWith('project://') ? (
                <MenuItem
                    asChild
                    onClick={(e: React.MouseEvent<HTMLElement>) => {
                        e.stopPropagation()
                        if (
                            checkedItemsArray.length > 0 &&
                            checkedItemsArray.find(({ id }) => id === item.record?.id)
                        ) {
                            openMoveToModal(checkedItemsArray)
                        } else {
                            openMoveToModal([item.record as unknown as FileSystemEntry])
                        }
                    }}
                >
                    <ButtonPrimitive menuItem>Move to...</ButtonPrimitive>
                </MenuItem>
            ) : null}

            {(item.id.startsWith('project/') || item.id.startsWith('project://')) && item.record?.type !== 'folder' ? (
                <MenuItem
                    asChild
                    onClick={(e: React.MouseEvent<HTMLElement>) => {
                        e.stopPropagation()
                        if (
                            checkedItemsArray.length > 0 &&
                            checkedItemsArray.find(({ id }) => id === item.record?.id)
                        ) {
                            openLinkToModal(checkedItemsArray)
                        } else {
                            openLinkToModal([item.record as unknown as FileSystemEntry])
                        }
                    }}
                >
                    <ButtonPrimitive menuItem>Create shortcut in...</ButtonPrimitive>
                </MenuItem>
            ) : null}

            {item.record?.path &&
            item.record?.type === 'folder' &&
            !(item.id.startsWith('shortcuts://') || item.id.startsWith('shortcuts/')) ? (
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        setEditingItemId(item.id)
                    }}
                    data-attr="tree-item-menu-rename-button"
                >
                    <ButtonPrimitive menuItem>Rename</ButtonPrimitive>
                </MenuItem>
            ) : null}

            {item.record?.path && item.record?.shortcut ? (
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        assureVisibility({ type: item.record?.type, ref: item.record?.ref })
                    }}
                    data-attr="tree-item-menu-show-original-button"
                >
                    <ButtonPrimitive menuItem>Show original</ButtonPrimitive>
                </MenuItem>
            ) : null}

            {item.record?.shortcut ? (
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        deleteItem(item.record as unknown as FileSystemEntry, logicKey ?? uniqueKey)
                    }}
                    data-attr="tree-item-menu-delete-shortcut-button"
                >
                    <ButtonPrimitive menuItem>Delete shortcut</ButtonPrimitive>
                </MenuItem>
            ) : item.record?.path &&
              item.record?.type === 'folder' &&
              !(item.id.startsWith('shortcuts://') || item.id.startsWith('shortcuts/')) ? (
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        deleteItem(item.record as unknown as FileSystemEntry, logicKey ?? uniqueKey)
                    }}
                    data-attr="tree-item-menu-delete-folder-button"
                >
                    <ButtonPrimitive menuItem>Delete folder</ButtonPrimitive>
                </MenuItem>
            ) : root === 'persons://' && item.record?.category === 'Groups' && item.record?.href ? (
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        const href = item.record?.href as string
                        const groupTypeIndex = parseInt(href.match(/\/groups\/(\d+)/)?.[1] || '0', 10)
                        const groupType = Array.from(groupTypes.values()).find(
                            (gt) => gt.group_type_index === groupTypeIndex
                        )

                        openDeleteGroupTypeDialog({
                            onConfirm: () => deleteGroupType(groupTypeIndex),
                            groupTypeName: groupType?.group_type || item.name || 'group type',
                        })
                    }}
                    data-attr="tree-item-menu-delete-group-button"
                >
                    <ButtonPrimitive menuItem>Delete group type</ButtonPrimitive>
                </MenuItem>
            ) : null}
        </>
    )
}
