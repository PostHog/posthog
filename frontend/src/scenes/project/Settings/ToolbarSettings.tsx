import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch } from '@posthog/lemon-ui'

export function ToolbarSettings(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSwitch
            id="posthog-toolbar-switch"
            onChange={() => {
                updateUser({
                    toolbar_mode: user?.toolbar_mode === 'disabled' ? 'toolbar' : 'disabled',
                })
            }}
            checked={user?.toolbar_mode !== 'disabled'}
            disabled={userLoading}
            label="Enable PostHog Toolbar"
            bordered
        />
    )
}
