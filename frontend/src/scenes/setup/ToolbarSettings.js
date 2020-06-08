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
                        Preference saved.
                    </span>
                )}
            </label>
            <p>You will see a small round PostHog button on your site. Click it to open the toolbar.</p>
            <br />
            <br />
        </div>
    )
}
