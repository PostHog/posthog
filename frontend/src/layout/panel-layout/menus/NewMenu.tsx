import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconFolder } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

export interface NewMenuProps {
    type: 'context' | 'dropdown'
    item?: TreeDataItem
    createFolder?: (path: string) => void
}

export function NewMenu({ type, item, createFolder }: NewMenuProps): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)
    const { setLastNewFolder } = useActions(projectTreeDataLogic)

    const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem
    const MenuSeparator = type === 'context' ? ContextMenuSeparator : DropdownMenuSeparator
    const MenuSub = type === 'context' ? ContextMenuSub : DropdownMenuSub
    const MenuSubTrigger = type === 'context' ? ContextMenuSubTrigger : DropdownMenuSubTrigger
    const MenuSubContent = type === 'context' ? ContextMenuSubContent : DropdownMenuSubContent

    return (
        <>
            {createFolder && item ? (
                <>
                    <MenuItem
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            createFolder(item?.record?.path)
                        }}
                        data-attr="tree-item-menu-new-folder-button"
                    >
                        <ButtonPrimitive menuItem>
                            <IconFolder />
                            Folder
                        </ButtonPrimitive>
                    </MenuItem>
                    <MenuSeparator />
                </>
            ) : null}
            {treeItemsNew.map((treeItem): JSX.Element => {
                if (treeItem.children) {
                    return (
                        <MenuSub key={treeItem.id}>
                            <MenuSubTrigger asChild inset>
                                <ButtonPrimitive menuItem data-attr="tree-item-menu-new-sub-menu-button">
                                    {treeItem.name || treeItem.id.charAt(0).toUpperCase() + treeItem.id.slice(1)}
                                    ...
                                    <IconChevronRight className="ml-auto size-3" />
                                </ButtonPrimitive>
                            </MenuSubTrigger>
                            <MenuSubContent>
                                {treeItem.children.map((child) => (
                                    <MenuItem
                                        key={child.id}
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            const folder = item?.record?.path
                                            if (folder) {
                                                setLastNewFolder(folder)
                                            }
                                            if (child.record?.href) {
                                                router.actions.push(
                                                    typeof child.record.href === 'function'
                                                        ? child.record.href(child.record.ref)
                                                        : child.record.href
                                                )
                                            }
                                        }}
                                        data-attr={`tree-item-menu-new-sub-menu-${child.name}-button`}
                                    >
                                        <ButtonPrimitive menuItem className="capitalize">
                                            {child.icon}
                                            {child.name}
                                        </ButtonPrimitive>
                                    </MenuItem>
                                ))}
                            </MenuSubContent>
                        </MenuSub>
                    )
                }
                return (
                    <MenuItem
                        key={treeItem.id}
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            const folder = item?.record?.path
                            if (folder) {
                                setLastNewFolder(folder)
                            }
                            if (treeItem.record?.href) {
                                router.actions.push(
                                    typeof treeItem.record.href === 'function'
                                        ? treeItem.record.href(treeItem.record.ref)
                                        : treeItem.record.href
                                )
                            }
                        }}
                    >
                        <ButtonPrimitive menuItem data-attr={`tree-item-menu-new-${treeItem.name}-button`}>
                            {treeItem.icon}
                            {treeItem.name}
                        </ButtonPrimitive>
                    </MenuItem>
                )
            })}
        </>
    )
}
