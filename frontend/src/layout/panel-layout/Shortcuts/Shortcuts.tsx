import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { AddShortcutModal } from '~/layout/panel-layout/Shortcuts/AddShortcutModal'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export function Shortcuts(): JSX.Element {
    const { shortcuts, shortcutsLoading } = useValues(shortcutsLogic)
    const { showModal, deleteShortcut } = useActions(shortcutsLogic)
    const { mainContentRef, isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

    const renderMenuItems = (item: TreeDataItem, type: 'context' | 'dropdown'): JSX.Element => {
        const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem
        const MenuSeparator = type === 'context' ? ContextMenuSeparator : DropdownMenuSeparator
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
                        void navigator.clipboard.writeText(document.location.origin + item.record?.href)
                    }}
                >
                    <ButtonPrimitive menuItem>Copy link address</ButtonPrimitive>
                </MenuItem>
                <MenuSeparator />
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        item.record && deleteShortcut((item.record as FileSystemEntry).id)
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
                    <div className="flex items-center gap-1">
                        <span className="text-xs font-semibold text-quaternary">Shortcuts</span>
                        {shortcutsLoading && shortcuts.length > 0 ? <Spinner /> : null}
                    </div>
                    <ButtonPrimitive onClick={showModal} iconOnly>
                        <IconPlus className="size-3 text-secondary" />
                    </ButtonPrimitive>
                </div>
            )}

            {isLayoutNavCollapsed && (
                <ButtonPrimitive onClick={showModal} iconOnly tooltip="Add shortcut" tooltipPlacement="right">
                    <IconPlus className="size-3 text-secondary" />
                </ButtonPrimitive>
            )}

            {!isLayoutNavCollapsed && shortcuts.length === 0 ? (
                <div className="pl-3 text-secondary">{shortcutsLoading ? <Spinner /> : 'No shortcuts added'}</div>
            ) : null}

            <div className="mt-[-0.25rem]">
                {/* TODO: move this tree into popover if isLayoutNavCollapsed is true */}
                <LemonTree
                    ref={treeRef}
                    contentRef={mainContentRef as RefObject<HTMLElement>}
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
            </div>
            <AddShortcutModal />
        </>
    )
}
