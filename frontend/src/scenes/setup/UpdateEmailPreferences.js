import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from '../userLogic'
import api from '../../lib/api'

export function UpdateEmailPreferences() {
    const { user } = useValues(userLogic)
    const { userUpdateRequest } = useActions(userLogic)
    const [saved, setSaved] = useState(false)

    return (
        <div>
            <label>
                <input
                    type="checkbox"
                    onChange={e => {
                        // TODO: refactor so we arent re rendering multiple times
                        userUpdateRequest({ user: { email_opt_in: !user.email_opt_in } })
                        setSaved(true)
                    }}
                    defaultChecked={user.email_opt_in}
                />
                &nbsp;Tick this box to receive security and feature updates via email. You can easily unsubscribe at any
                time.
            </label>
            {saved && <p className="text-success">Preference saved.</p>}
            <br />
            <br />
        </div>
    )
}
