import React from 'react'
import { useValues, useActions } from 'kea'
import { Switch } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
            <Switch
                // @ts-expect-error - id works just fine despite not being in CompoundedComponent
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
