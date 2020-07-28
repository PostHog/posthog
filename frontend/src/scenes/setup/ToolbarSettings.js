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
                Try the new PostHog Toolbar
            </label>
            {saved && (
                <p className="text-success" style={{ marginTop: 10 }}>
                    Preference saved.
                    {user.toolbar_mode === 'toolbar' && <> Please click the "Launch Toolbar" link in the sidebar!</>}
                </p>
            )}
            <p>
                The Toolbar gives you access to heatmaps, stats and allows you to create actions, without ever leaving
                your own website or app! Make sure you're using the snippet or the latest <code>posthog-js</code>{' '}
                version.
            </p>
            <p>
                To ask questions and to provide feedback during the beta program, please{' '}
                <a href="https://github.com/PostHog/posthog/issues/1129" target="_blank" rel="noreferrer noopener">
                    click here
                </a>
                !
            </p>
            <br />
            <br />
        </div>
    )
}
