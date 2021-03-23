import React from 'react'
import { Button, Modal } from 'antd'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from './navigation/navigationLogic'

export function ChangelogModal({ onDismiss }: { onDismiss: () => void }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { latestVersion } = useValues(navigationLogic)

    if (user?.is_multi_tenancy) {
        // The changelog is not available on cloud
        return null
    }

    return (
        <Modal
            visible
            onOk={onDismiss}
            onCancel={onDismiss}
            footer={<Button onClick={onDismiss}>Close</Button>}
            style={{ top: 20, minWidth: '70%', fontSize: 16 }}
        >
            <span>
                You're on version <b>{user?.posthog_version}</b> of PostHog.{' '}
                {latestVersion &&
                    (latestVersion === user?.posthog_version ? (
                        'This is the newest version.'
                    ) : (
                        <span className="text-warning">
                            The newest version is <b>{latestVersion}</b>.
                        </span>
                    ))}
            </span>
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
