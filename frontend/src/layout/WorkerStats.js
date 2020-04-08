import React, { useEffect, useState } from 'react'
import api from './../lib/api'
import { Modal } from 'lib/components/Modal'

export function WorkerStats() {
    const [heartbeat, setHeartbeat] = useState(null)
    const [showErrorModal, setShowErrorModal] = useState(false)

    function updateHeartbeat() {
        api.get('_stats/')
            .then(stats => {
                const { worker_heartbeat: workerHeartbeat } = stats
                setHeartbeat(workerHeartbeat)
            })
            .catch(error => {
                setHeartbeat('error')
            })
    }

    useEffect(() => {
        updateHeartbeat()
    }, [])

    return heartbeat !== null ? (
        <span style={{ marginRight: 32, marginLeft: -16 }}>
            {heartbeat === 'offline' || heartbeat === 'error' ? (
                <span style={{ color: 'red', cursor: 'pointer' }} onClick={() => setShowErrorModal(true)}>
                    ‼️ Worker OFFLINE ‼️
                </span>
            ) : heartbeat > 90 ? (
                <span style={{ color: 'orange', cursor: 'pointer' }} onClick={() => setShowErrorModal(true)}>
                    ⚠️ Worker delayed
                </span>
            ) : (
                <span style={{ color: 'green' }}>Worker online!</span>
            )}
            {showErrorModal ? (
                <Modal onDismiss={() => setShowErrorModal(false)}>
                    <h2>Worker Error</h2>
                    <p>
                        Starting with <strong>version 1.1.0</strong> every installation of PostHog will require a
                        background worker to work properly.
                    </p>
                    <p>We have detected an error with your worker setup.</p>
                    <p>
                        Please{' '}
                        <a
                            href="https://docs.posthog.com/#/upgrading-posthog?id=upgrading-from-before-1011"
                            target="_blank"
                            rel="noopener"
                        >
                            see the documentation
                        </a>{' '}
                        for more information
                    </p>
                </Modal>
            ) : null}
        </span>
    ) : null
}
