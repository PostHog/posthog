import React from 'react'
import { Button, Modal } from 'antd'
import { useValues } from 'kea'
import { navigationLogic } from './navigation/navigationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export interface ChangelogModalProps {
    onDismiss: () => void
    visible?: boolean
}

export function ChangelogModal({ onDismiss, visible }: ChangelogModalProps): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { latestVersion } = useValues(navigationLogic)

    if (preflight?.cloud) {
        // The changelog is not available on cloud
        return null
    }

    return (
        <Modal
            visible={visible}
            onOk={onDismiss}
            onCancel={onDismiss}
            footer={<Button onClick={onDismiss}>Close</Button>}
            style={{ top: 20, minWidth: '70%', fontSize: 16 }}
        >
            <span>
                You're on version <b>{preflight?.posthog_version}</b> of PostHog.{' '}
                {latestVersion &&
                    (latestVersion === preflight?.posthog_version ? (
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
