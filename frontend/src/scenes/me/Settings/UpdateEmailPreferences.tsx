import React from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
            <LemonSwitch
                id="email-preferences"
                data-attr="email-preferences"
                onChange={() => {
                    updateUser({ email_opt_in: !user?.email_opt_in })
                }}
                defaultChecked={user?.email_opt_in}
                loading={userLoading}
                disabled={userLoading}
            />
            <label
                htmlFor="email-preferences"
                style={{
                    marginLeft: '10px',
                }}
            >
                Receive security and feature updates via email. You can easily unsubscribe at any time.
            </label>
        </div>
    )
}
