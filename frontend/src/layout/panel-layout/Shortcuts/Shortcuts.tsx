import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { AddShortcutModal } from '~/layout/panel-layout/Shortcuts/AddShortcutModal'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export function Shortcuts(): JSX.Element {
    const { shortcuts } = useValues(shortcutsLogic)
    const { showModal, deleteShortcut } = useActions(shortcutsLogic)
    const { mainContentRef, isLayoutNavCollapsed } = useValues(panelLayoutLogic)

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
                        item.record && deleteShortcut(item.record as FileSystemEntry)
                    }}
                >
                    <ButtonPrimitive menuItem>Delete shortcut</ButtonPrimitive>
                </MenuItem>
            </>
        )
    }

    return (
        <>
            {!isLayoutNavCollapsed && (
                <div className="flex justify-between items-center pl-3 pr-1 relative">
                    <span className="text-xs font-semibold text-quaternary">Shortcuts</span>
                    <ButtonPrimitive onClick={showModal}>
                        <IconPlus className="size-3 text-secondary" />
                    </ButtonPrimitive>
                </div>
            )}
            {shortcuts.length === 0 && <div className="pl-3 text-muted">No shortcuts added</div>}
            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={shortcuts}
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
                    node?.onClick?.(true)
                }}
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
            />
            <AddShortcutModal />
        </>
    )
}
