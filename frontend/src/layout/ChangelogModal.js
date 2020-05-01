import React from 'react'
import { Modal } from '../lib/components/Modal'

export function ChangelogModal({ onDismiss }) {
    return (
        <Modal onDismiss={onDismiss}>
            <iframe
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
