import React, { useEffect, useState } from 'react'
import api from './../lib/api'
import { Modal, Button } from 'antd'

export function WorkerStats() {
    const [heartbeat, setHeartbeat] = useState(null)
    const [showErrorModal, setShowErrorModal] = useState(false)

    function updateHeartbeat() {
        api.get('_stats/')
            .then(stats => {
                const { worker_heartbeat: workerHeartbeat } = stats
                setHeartbeat(workerHeartbeat)
            })
            .catch(() => {
                setHeartbeat('error')
            })
    }

    useEffect(() => {
        updateHeartbeat()
    }, [])

    return heartbeat !== null ? (
        <span style={{ marginRight: 32, marginLeft: -16 }}>
            {heartbeat === 'offline' || heartbeat === 'error' || heartbeat > 90 ? (
                <span
                    style={{
                        color: heartbeat === 'offline' || heartbeat === 'error' ? 'red' : 'orange',
                        cursor: 'pointer',
                    }}
                    onClick={() => setShowErrorModal(true)}
                >
                    ⚠️ Configuration Error
                </span>
            ) : null}
            <Modal visible={showErrorModal} footer={<Button onClick={() => setShowErrorModal(false)}>Close</Button>}>
                <h2>Configuration Issue</h2>
                <p>
                    Starting with <strong>PostHog 1.1.0</strong>, every installation <em>requires</em> a background
                    worker to function properly.
                </p>
                <p>
                    We can't seem to reach your worker. There could be a few reasons for this.
                    <ol>
                        <li>Your Redis server wasn't started or is down</li>
                        <li>Your worker wasn't started or is down</li>
                        <li>Your web server has trouble reaching Redis</li>
                    </ol>
                </p>
                <p>
                    Please{' '}
                    <a
                        href="https://docs.posthog.com/#/upgrading-posthog?id=upgrading-from-before-1011"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        see the documentation
                    </a>{' '}
                    for more information
                </p>
            </Modal>
        </span>
    ) : null
}
