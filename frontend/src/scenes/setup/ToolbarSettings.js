import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from '../userLogic'
import { Switch } from 'antd'

export function ToolbarSettings() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            <Switch
                onChange={() => {
                    userUpdateRequest({
                        user: {
                            toolbar_mode: user.toolbar_mode === 'toolbar' ? 'default' : 'toolbar',
                        },
                    })
                    setSaved(true)
                }}
                defaultChecked={user.toolbar_mode === 'toolbar'}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Try the new PostHog Toolbar?
                {saved && (
                    <span className="text-success" style={{ marginLeft: 10 }}>
                        Preference saved. You might need to restart your browser for the change to take effect.
                    </span>
                )}
            </label>
            <p>
                The toolbar gives you access to heatmaps, stats and allows you to create actions, without ever leaving
                your own website or app! Make sure you're using the snippet or the latest posthog-js.
            </p>
            <br />
            <br />
        </div>
    )
}
