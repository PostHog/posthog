import { useActions, useValues } from 'kea'
import { FileSelect } from 'lib/components/FileSelect/FileSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { shortcutsLogic } from '~/layout/panel-layout/Shortcuts/shortcutsLogic'

export function AddShortcutModal(): JSX.Element {
    const { selectedItem, modalVisible } = useValues(shortcutsLogic)
    const { hideModal, setSelectedItem, addShortcutItem } = useActions(shortcutsLogic)

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
                        <LemonButton type="primary" onClick={() => selectedItem && addShortcutItem(selectedItem)}>
                            Add {selectedItem?.path || 'Project root'}
                        </LemonButton>
                    </>
                ) : null
            }
        >
            <div className="w-192 max-w-full">
                <FileSelect value={selectedItem?.id} onChange={setSelectedItem} />
            </div>
        </LemonModal>
    )
}
