import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

export function HumanFriendlyComparisonPeriodsSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <>
            <p>
                When comparing against a previous month or year, PostHog will use the same start and end dates as the
                current period by default. It might be desirable, however, to compare against the same day of the week
                instead of the same day to account for weekend seasonality. If that's the case for your analysis, you
                can enable this setting.
            </p>
            <p>
                In practice, this means that an year comparison becomes a 52 week comparison, and a month comparison
                becomes a 4 week comparison.
            </p>
            <LemonSwitch
                onChange={(checked) => {
                    updateCurrentTeam({ human_friendly_comparison_periods: checked })
                }}
                checked={!!currentTeam?.human_friendly_comparison_periods}
                disabled={currentTeamLoading}
                label="Use human friendly comparison periods"
                bordered
            />
        </>
    )
}
