import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { webAnalyticsAchievementsPreferencesLogic } from 'scenes/web-analytics/achievements/webAnalyticsAchievementsPreferencesLogic'

export function WebAnalyticsAchievementsSetting(): JSX.Element {
    const { achievementsOptOut, preferencesLoading } = useValues(webAnalyticsAchievementsPreferencesLogic)
    const { setAchievementsOptOut } = useActions(webAnalyticsAchievementsPreferencesLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => setAchievementsOptOut({ optedOut: !checked })

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Show Web analytics achievements"
                checked={!achievementsOptOut}
                onCheckedChange={handleChange}
                disabled={preferencesLoading}
            />
        )
    }

    return (
        <LemonSwitch
            onChange={handleChange}
            checked={!achievementsOptOut}
            loading={preferencesLoading}
            label="Show Web analytics achievements"
            bordered
        />
    )
}
