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
                const response = await api.get('api/organizations/@current/plugins/status')
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
            {!user?.is_multi_tenancy && (
                <>
                    <div style={{ marginBottom: 20 }}>
                        Plugin support requires the cooperation of the main PostHog application and the{' '}
                        <a href="https://github.com/PostHog/plugin-server" target="_blank" rel="noreferrer noopener">
                            <code>PostHog plugin server</code>
                        </a>
                        , which must be properly set up.
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
                                <WarningOutlined /> Offline –{' '}
                                <a
                                    href="https://posthog.com/docs/plugins/enabling#plugin-server-is-offline"
                                    target="_blank"
                                    rel="noreferrer noopener"
                                >
                                    Why could this be?
                                </a>
                            </span>
                        )}
                    </div>
                </>
            )}
            <div style={{ marginBottom: 20 }}>
                <Checkbox checked={optIn} onChange={() => setOptIn(!optIn)} disabled={serverStatus !== 'online'}>
                    I wish to enable plugins for <b>{user?.team?.name}</b>.
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
