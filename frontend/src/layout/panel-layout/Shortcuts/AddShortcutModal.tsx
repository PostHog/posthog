import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export function CombinedTree(): JSX.Element {
    const { mainContentRef } = useValues(panelLayoutLogic)
    const { selectedItem, treeItemsCombined } = useValues(shortcutsLogic)
    const { setSelectedItem } = useActions(shortcutsLogic)
    const { loadFolderIfNotLoaded } = useActions(projectTreeLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

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
                        <LemonButton
                            type="primary"
                            onClick={() =>
                                selectedItem?.record && addShortcutItem(selectedItem?.record as FileSystemEntry)
                            }
                        >
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
