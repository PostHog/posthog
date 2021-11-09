import React from 'react'
import { useValues } from 'kea'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { userLogic } from 'scenes/userLogic'
import { ToolbarSettings } from 'scenes/project/Settings/ToolbarSettings'
import { Modal, ModalProps } from 'antd'

export function ToolbarModal({ visible, onCancel }: Pick<ModalProps, 'visible' | 'onCancel'>): JSX.Element {
    const { user } = useValues(userLogic)
    const toolbarEnabled = user?.toolbar_mode !== 'disabled'

    return (
        <Modal
            title={toolbarEnabled ? 'Toolbar – permitted domains/URLs' : 'Enable Toolbar'}
            visible={visible}
            onCancel={onCancel}
            footer={null}
        >
            {toolbarEnabled ? (
                <>
                    <p>
                        Make sure you're using the snippet or the latest <code>posthog-js</code> version.
                        <br />
                        Clicking a URL launches it with the Toolbar.
                    </p>
                    <EditAppUrls allowNavigation />
                </>
            ) : (
                <ToolbarSettings />
            )}
        </Modal>
    )
}
