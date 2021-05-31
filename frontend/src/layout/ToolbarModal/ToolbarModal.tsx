import React from 'react'
import { useValues } from 'kea'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { userLogic } from 'scenes/userLogic'
import { ToolbarSettings } from 'scenes/project/Settings/ToolbarSettings'
import { Modal } from 'antd'

interface ToolbarModalProps {
    visible: boolean
    onClose: () => void
}

export function ToolbarModal({ visible, onClose }: ToolbarModalProps): JSX.Element {
    const { user } = useValues(userLogic)
    const toolbarEnabled = user?.toolbar_mode !== 'disabled'

    return (
        <Modal
            visible={visible}
            title={
                user?.toolbar_mode !== 'disabled'
                    ? 'Toolbar – Permitted Domains/URLs'
                    : 'Enable the Toolbar to continue'
            }
            footer={null}
            onCancel={onClose}
        >
            {!toolbarEnabled ? (
                <ToolbarSettings />
            ) : (
                <>
                    <p>
                        Make sure you're using the snippet or the latest <code>posthog-js</code> version.
                        <br />
                        Clicking a URL launches it with the Toolbar.
                    </p>
                    <EditAppUrls allowNavigation />
                </>
            )}
        </Modal>
    )
}
