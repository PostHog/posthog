import React from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch } from '@posthog/lemon-ui'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
            <LemonSwitch
                data-attr="email-preferences"
                onChange={() => {
                    updateUser({ email_opt_in: !user?.email_opt_in })
                }}
                checked={user?.email_opt_in}
                disabled={userLoading}
                label="Receive security and feature updates via email. You can easily unsubscribe at any time."
                fullWidth
                bordered
            />
            <br />

            <LemonSwitch
                id="plugin-disabled"
                data-attr="plugin_disabled"
                onChange={() => {
                    updateUser({ notifications_plugin_disabled: !user?.notifications_plugin_disabled })
                }}
                checked={user?.notifications_plugin_disabled}
                disabled={userLoading}
                fullWidth
                bordered
                label="Get notified when plugins are disabled due to errors."
            />
        </div>
    )
}
