import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'

export function GameTree(): JSX.Element {
    const { treeItemsGames } = useValues(projectTreeLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)
    const { addShortcutItem } = useActions(shortcutsLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

    const renderMenuItems = (item: TreeDataItem, type: 'context' | 'dropdown'): JSX.Element => {
        const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem

        return (
            <>
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        window.open(item.record?.href, '_blank')
                    }}
                >
                    <ButtonPrimitive menuItem>Open link in new tab</ButtonPrimitive>
                </MenuItem>
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        item.record && addShortcutItem(item.record as FileSystemEntry)
                    }}
                >
                    <ButtonPrimitive menuItem>Add to shortcuts panel</ButtonPrimitive>
                </MenuItem>
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        void navigator.clipboard.writeText(document.location.origin + item.record?.href)
                    }}
                >
                    <ButtonPrimitive menuItem>Copy link address</ButtonPrimitive>
                </MenuItem>
            </>
        )
    }

    return (
        <PanelLayoutPanel>
            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={treeItemsGames}
                itemContextMenu={(item) => {
                    return <ContextMenuGroup>{renderMenuItems(item, 'context')}</ContextMenuGroup>
                }}
                itemSideAction={(item) => {
                    return <DropdownMenuGroup>{renderMenuItems(item, 'dropdown')}</DropdownMenuGroup>
                }}
                onFolderClick={(folder) => {
                    if (folder?.id) {
                        if (expandedFolders.includes(folder.id)) {
                            setExpandedFolders(expandedFolders.filter((id) => id !== folder.id))
                        } else {
                            setExpandedFolders([...expandedFolders, folder.id])
                        }
                    }
                }}
                onItemClick={(node) => {
                    if (node?.record?.href) {
                        router.actions.push(
                            typeof node.record.href === 'function'
                                ? node.record.href(node.record.ref)
                                : node.record.href
                        )
                    }
                    node?.onClick?.(true)
                }}
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
            />
        </PanelLayoutPanel>
    )
}
