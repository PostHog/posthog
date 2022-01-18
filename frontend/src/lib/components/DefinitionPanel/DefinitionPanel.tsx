import React from 'react'
import { useActions, useValues } from 'kea'
import { definitionPanelLogic } from 'lib/components/DefinitionPanel/definitionPanelLogic'
import { Modal } from 'antd'

export function DefinitionPanel(): JSX.Element {
    const { visible, definition } = useValues(definitionPanelLogic)
    const { closeDrawer } = useActions(definitionPanelLogic)
    return (
        <Modal className="click-outside-block" title="Definition Panel" visible={visible} onCancel={closeDrawer}>
            {JSON.stringify(definition)}
        </Modal>
    )
}
