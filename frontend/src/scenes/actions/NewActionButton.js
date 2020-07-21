import React, { useState } from 'react'
import { Button } from 'antd'
import { NewActionModal } from './NewActionModal'

export function NewActionButton() {
    let [visible, setVisible] = useState(false)
    return (
        <>
            <Button type="primary" onClick={() => setVisible(true)} data-attr="create-action">
                + New Action
            </Button>
            <NewActionModal visible={visible} onVisibleChanged={(visible) => setVisible(visible)}></NewActionModal>
        </>
    )
}
