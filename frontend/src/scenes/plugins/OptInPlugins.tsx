import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Checkbox, Spin } from 'antd'
import { CheckOutlined, WarningOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import api from 'lib/api'
import posthog from 'posthog-js'

export function OptInPlugins(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)
    const [optIn, setOptIn] = useState(false)
    const [serverStatus, setServerStatus] = useState('loading')

    useEffect(() => {
        async function setStatus(): Promise<void> {
            try {
                const response = await api.get('api/plugin/status')
                setServerStatus(response.status)
            } catch (e) {
                setServerStatus('offline')
            }
        }
        setStatus()
        const interval = window.setInterval(setStatus, 5000)
        return () => window.clearInterval(interval)
    }, [])

    return (
        <div>
            <div style={{ marginBottom: 20 }}>
                Plugins enable you to extend PostHog's core functionality. For example by adding geographical
                information to your events, normalizing your revenue information to a single currency, etc.
            </div>
            <div style={{ marginBottom: 20 }}>
                Plugins are currently in an <strong>experimental</strong> stage. You must opt-in to use them in{' '}
                <b>each project.</b>
            </div>
            {!user?.is_multi_tenancy && (
                <>
                    <div style={{ marginBottom: 20 }}>
                        Plugin support requires the cooperation of the main PostHog application and the new NodeJS-based{' '}
                        <a
                            href="https://github.com/PostHog/posthog-plugin-server"
                            target="_blank"
                            rel="noreferrer noopener"
                        >
                            <code>posthog-plugin-server</code>
                        </a>
                        . In case the plugin server is not properly configured, you <em>might</em> experience data loss.
                        If you do not wish to take this risk we recommend waiting a few weeks until this functionality
                        is fully released.
                    </div>
                    <div style={{ marginBottom: 20 }}>
                        Plugin server:{' '}
                        {serverStatus === 'loading' ? (
                            <Spin />
                        ) : serverStatus === 'online' ? (
                            <span style={{ color: 'var(--green)' }}>
                                <CheckOutlined /> Online
                            </span>
                        ) : (
                            <span style={{ color: 'var(--red)' }}>
                                <WarningOutlined /> Offline
                            </span>
                        )}
                    </div>
                </>
            )}
            <div style={{ marginBottom: 20 }}>
                <Checkbox checked={optIn} onChange={() => setOptIn(!optIn)} disabled={serverStatus !== 'online'}>
                    I understand the risks and wish to try this beta feature now for <b>{user?.team?.name}</b>.
                </Checkbox>
            </div>
            <div>
                <Button
                    type="primary"
                    disabled={!optIn || serverStatus !== 'online'}
                    data-attr="enable-plugins"
                    onClick={() => {
                        userUpdateRequest({ team: { plugins_opt_in: true } })
                        posthog.capture('plugins enabled for project')
                    }}
                >
                    Enable plugins for this project
                </Button>
            </div>
        </div>
    )
}
