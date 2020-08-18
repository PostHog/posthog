import React from 'react'
import { Button, Modal } from 'antd'
import { useValues } from 'kea'
import { useLatestVersion } from 'lib/hooks/useLatestVersion'
import { userLogic } from 'scenes/userLogic'

export function ChangelogModal({ onDismiss }: { onDismiss: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const latestVersion = useLatestVersion(user?.posthog_version)

    return (
        <Modal
            visible
            onOk={onDismiss}
            onCancel={onDismiss}
            footer={<Button onClick={onDismiss}>Close</Button>}
            style={{ top: 20, minWidth: '70%', fontSize: 16 }}
        >
            {!window.location.href.includes('app.posthog.com') ? (
                <span>
                    You're on version <b>{user?.posthog_version}</b> of PostHog.{' '}
                    {latestVersion &&
                        (latestVersion === user?.posthog_version ? (
                            'This is the newest version.'
                        ) : (
                            <>
                                The newest version is <b>{latestVersion}</b>.
                            </>
                        ))}
                </span>
            ) : (
                <span>You're on the newest version of PostHog.</span>
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
