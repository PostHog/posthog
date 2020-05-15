import React, { useEffect, useState } from 'react'
import api from './../lib/api'
import { Modal, Button } from 'antd'
import { WarningOutlined } from '@ant-design/icons'

export function WorkerStats() {
    const [heartbeat, setHeartbeat] = useState(null)
    const [modalVisible, setModalVisible] = useState(false)

    const openModal = () => setModalVisible(true)
    const closeModal = () => setModalVisible(false)

    async function updateHeartbeat() {
        try {
            const stats = await api.get('_stats/')
            setHeartbeat(stats.worker_heartbeat)
        } catch (error) {
            setHeartbeat('error')
        }
    }

    useEffect(() => {
        updateHeartbeat()
        const interval = window.setInterval(updateHeartbeat, 30000)
        return () => window.clearInterval(interval)
    }, [])

    return heartbeat !== null ? (
        <span style={{ marginRight: 32, marginLeft: -16 }}>
            {heartbeat === 'offline' || heartbeat === 'error' || heartbeat > 90 ? (
                <span
                    style={{
                        color: heartbeat === 'offline' || heartbeat === 'error' ? 'red' : 'orange',
                        cursor: 'pointer',
                    }}
                    onClick={openModal}
                >
                    <WarningOutlined />
                    <span className="hide-when-small"> Configuration Error</span>
                </span>
            ) : null}
            <Modal
                visible={modalVisible}
                onOk={closeModal}
                onCancel={closeModal}
                footer={<Button onClick={closeModal}>Close</Button>}
            >
                <h2>Configuration Issue</h2>
                <p>
                    Starting with <strong>PostHog 1.1.0</strong>, every installation <em>requires</em> a background
                    worker to function properly.
                </p>
                <p>We can't seem to reach your worker. There could be a few reasons for this.</p>
                <ol>
                    <li>Your Redis server wasn't started or is down</li>
                    <li>Your worker wasn't started or is down</li>
                    <li>Your web server has trouble reaching Redis</li>
                </ol>
                <p>
                    Please{' '}
                    <a
                        href="https://posthog.com/docs/deployment/upgrading-posthog#upgrading-from-before-1011"
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
