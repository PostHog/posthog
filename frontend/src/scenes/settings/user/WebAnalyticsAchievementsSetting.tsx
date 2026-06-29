import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSwitch } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

export function WebAnalyticsAchievementsSetting(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSwitch
            onChange={(checked) => {
                const optedOut = !checked
                updateUser({ web_analytics_achievements_opt_out: optedOut })
                posthog.setPersonProperties({ web_analytics_achievements_opt_out: optedOut })
                posthog.capture('web_analytics_achievements_opt_out_toggled', { opted_out: optedOut })
            }}
            checked={!user?.web_analytics_achievements_opt_out}
            loading={userLoading}
            label="Show Web analytics achievements"
            bordered
        />
    )
}
