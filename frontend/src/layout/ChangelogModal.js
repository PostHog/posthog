import React from 'react'
import { Button, Modal } from 'antd'

export function ChangelogModal({ onDismiss }) {
    return (
        <Modal
            visible
            onOk={onDismiss}
            onCancel={onDismiss}
            footer={<Button onClick={onDismiss}>Close</Button>}
            style={{ top: 20, minWidth: '70%' }}
        >
            <iframe
                data-attr="changelog-modal"
                style={{
                    border: 0,
                    width: '100%',
                    height: '80vh',
                    margin: '0 -1rem',
                }}
                src="https://update.posthog.com/changelog"
            />
        </Modal>
    )
}
