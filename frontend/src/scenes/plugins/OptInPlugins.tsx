import React, { useState } from 'react'
import { useActions } from 'kea'
import { Button, Checkbox } from 'antd'
import { ApiOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

export function OptInPlugins(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const [optIn, setOptIn] = useState(false)

    return (
        <div>
            <div style={{ marginBottom: 20 }}>
                Plugins enable you to extend PostHog's core functionality. For example by adding geographical
                information to your events, normalizing your revenue information to a single currency, etc.
            </div>
            <div style={{ marginBottom: 20 }}>
                Plugins are currently an <strong>experimental</strong> feature that you must opt in to.
            </div>
            <div style={{ marginBottom: 20 }}>
                Plugins support requires the cooperation of the main posthog application and a new nodejs based{' '}
                <a href="https://github.com/PostHog/posthog-plugins" target="_blank" rel="noreferrer noopener">
                    <code>posthog-plugin-server</code>
                </a>
                . In case the plugin server is not properly configured, you <em>might</em> experience data loss. Proceed
                at your own risk or wait a few weeks until we're out of beta.
            </div>
            <div style={{ marginBottom: 20 }}>
                <Checkbox checked={optIn} onChange={() => setOptIn(!optIn)}>
                    I understand the risks and I'm not worried about potentially losing a few events.
                </Checkbox>
            </div>
            <div>
                <Button
                    type="primary"
                    disabled={!optIn}
                    onClick={() => userUpdateRequest({ team: { plugins_opt_in: true } })}
                >
                    <ApiOutlined /> Enable plugins for this project
                </Button>
            </div>
        </div>
    )
}
