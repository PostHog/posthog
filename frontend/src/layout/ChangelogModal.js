import React from 'react'
import { Button, Modal } from 'antd'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function ChangelogModal({ onDismiss }) {
    const { user } = useValues(userLogic)
    return (
        <Modal
            visible
            onOk={onDismiss}
            onCancel={onDismiss}
            footer={<Button onClick={onDismiss}>Close</Button>}
            style={{ top: 20, minWidth: '70%', fontSize: 16 }}
        >
            {window.location.href.indexOf('app.posthog.com') === -1 ? (
                <span>
                    You're currently on version <strong>{user.posthog_version}</strong>
                </span>
            ) : (
                <span>You're on the latest version of PostHog.</span>
            )}
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
