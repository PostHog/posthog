import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { Switch } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function UpdateEmailPreferences() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            <Switch
                id="email-preferences"
                onChange={() => {
                    userUpdateRequest({ user: { email_opt_in: !user.email_opt_in } })
                    setSaved(true)
                }}
                defaultChecked={user.email_opt_in}
            />
            <label
                htmlFor="email-preferences"
                style={{
                    marginLeft: '10px',
                }}
            >
                Receive security and feature updates via email. You can easily unsubscribe at any time.
            </label>
            {saved && <p className="text-success">Preference saved.</p>}
        </div>
    )
}
