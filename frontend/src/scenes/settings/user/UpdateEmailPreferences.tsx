import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

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
                checked={user?.email_opt_in || false}
                disabled={userLoading}
                label="Receive security and feature updates via email. You can easily unsubscribe at any time."
                bordered
            />
            <br />

            <LemonSwitch
                id="plugin-disabled"
                data-attr="plugin_disabled"
                onChange={() => {
                    user?.notification_settings &&
                        updateUser({
                            notification_settings: {
                                ...user?.notification_settings,
                                plugin_disabled: !user?.notification_settings.plugin_disabled,
                            },
                        })
                }}
                checked={user?.notification_settings.plugin_disabled || false}
                disabled={userLoading}
                bordered
                label="Get notified when plugins are disabled due to errors."
            />
        </div>
    )
}
