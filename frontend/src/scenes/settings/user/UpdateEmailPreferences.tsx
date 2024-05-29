import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function UpdateEmailPreferences(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div>
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
                label="Get notified of data pipeline errors."
            />
        </div>
    )
}
