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
            {showErrorModal ? (
                <Modal onDismiss={() => setShowErrorModal(false)}>
                    <h2>Configuration Issue</h2>
                    <p>
                        Starting with <strong>PostHog 1.1.0</strong>, every installation <em>requires</em> a background
                        worker to function properly.
                    </p>
                    <p>
                        These workers will make PostHog a lot faster and will pave the road for other goodies, such as
                        slack integration, scheduled reports and free pizzas for everyone!
                    </p>
                    <p>
                        While workers are <em>currently</em> still optional, we <strong>strongly</strong> recommend you
                        already enable them to make the next upgrade painless.
                    </p>
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
