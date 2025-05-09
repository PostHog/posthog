import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTree, LemonTreeRef, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ContextMenuGroup, ContextMenuItem, ContextMenuSeparator } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'

export function CombinedTree(): JSX.Element {
    const { treeItemsCombined } = useValues(projectTreeLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)
    const { selectedItem } = useValues(shortcutsLogic)
    const { setSelectedItem, deleteShortcut } = useActions(shortcutsLogic)
    const { loadFolderIfNotLoaded } = useActions(projectTreeLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

    // Merge duplicate menu code for both context and dropdown menus
    const renderMenuItems = (item: TreeDataItem, type: 'context' | 'dropdown'): JSX.Element => {
        // Determine the separator component based on MenuItem type
        const MenuItem = type === 'context' ? ContextMenuItem : DropdownMenuItem
        const MenuSeparator = type === 'context' ? ContextMenuSeparator : DropdownMenuSeparator
        return (
            <>
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        deleteShortcut(item)
                    }}
                >
                    <ButtonPrimitive menuItem>Delete shortcut</ButtonPrimitive>
                </MenuItem>

                <MenuSeparator />
            </>
        )
    }
    return (
        <div className="bg-surface-primary p-2 border rounded-[var(--radius)] overflow-y-scroll h-[60vh] min-h-[200px]">
            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={treeItemsCombined}
                isItemActive={(item) => item.id === selectedItem?.id}
                onFolderClick={(folder) => {
                    if (folder?.id) {
                        loadFolderIfNotLoaded(folder?.id)
                        if (expandedFolders.includes(folder.id)) {
                            setExpandedFolders(expandedFolders.filter((id) => id !== folder.id))
                        } else {
                            setExpandedFolders([...expandedFolders, folder.id])
                        }
                        setSelectedItem(folder)
                    }
                }}
                itemContextMenu={(item) => {
                    return <ContextMenuGroup>{renderMenuItems(item, 'context')}</ContextMenuGroup>
                }}
                itemSideAction={(item) => {
                    return <DropdownMenuGroup>{renderMenuItems(item, 'dropdown')}</DropdownMenuGroup>
                }}
                onItemClick={(node, e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    node && setSelectedItem(node)
                }}
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
            />
        </div>
    )
}

export function AddShortcutModal(): JSX.Element {
    const { selectedItem, modalVisible } = useValues(shortcutsLogic)
    const { hideModal, addShortcutItem } = useActions(shortcutsLogic)

    return (
        <LemonModal
            onClose={hideModal}
            isOpen={modalVisible}
            title="Add to shortcuts"
            description="You are adding one item to shortcuts"
            footer={
                selectedItem ? (
                    <>
                        <div className="flex-1" />
                        <LemonButton type="primary" onClick={() => addShortcutItem(selectedItem)}>
                            Add {selectedItem?.name || 'Project root'}
                        </LemonButton>
                    </>
                ) : null
            }
        >
            <div className="w-192 max-w-full">
                <CombinedTree />
            </div>
        </LemonModal>
    )
}

export function Shortcuts(): JSX.Element {
    const { shortcuts } = useValues(shortcutsLogic)
    const { showModal } = useActions(shortcutsLogic)
    const { mainContentRef, isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

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
