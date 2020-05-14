import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from '../userLogic'
import { Switch } from 'antd'

export function UpdateEmailPreferences() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            <Switch
                onChange={() => {
                    userUpdateRequest({ user: { email_opt_in: !user.email_opt_in } })
                    setSaved(true)
                }}
                defaultChecked={user.email_opt_in}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Receive security and feature updates via email. You can easily unsubscribe at any time.
            </label>
            {saved && <p className="text-success">Preference saved.</p>}
            <br />
            <br />
        </div>
    )
}
