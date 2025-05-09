import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'

export function ProductTree(): JSX.Element {
    const { treeItemsProducts } = useValues(projectTreeLogic)
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
                        addShortcutItem(item)
                    }}
                >
                    <ButtonPrimitive menuItem>Add to shortcuts panel</ButtonPrimitive>
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
                data={treeItemsProducts}
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
