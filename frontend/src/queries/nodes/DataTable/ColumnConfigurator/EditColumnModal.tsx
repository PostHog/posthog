import { useActions, useValues } from 'kea'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { AnyDataNode } from '~/queries/schema/schema-general'

import { columnConfiguratorLogic } from './columnConfiguratorLogic'

export function EditColumnModal({ metadataSource }: { metadataSource: AnyDataNode }): JSX.Element {
    const { editingColumn, editingColumnIndex } = useValues(columnConfiguratorLogic)
    const { saveEditedColumn, closeColumnEditor } = useActions(columnConfiguratorLogic)

    return (
        <LemonModal
            isOpen={editingColumnIndex !== null}
            title="Edit column"
            onClose={closeColumnEditor}
            // Sits above the column configurator modal that opens it
            zIndex="1161"
            className="w-full max-w-160"
        >
            <HogQLEditor
                value={editingColumn}
                onChange={saveEditedColumn}
                metadataSource={metadataSource}
                submitText="Save column"
            />
        </LemonModal>
    )
}
