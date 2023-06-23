import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSelect } from '@posthog/lemon-ui'

export function WeekStartConfig(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <LemonSelect
            value={currentTeam?.week_start_day || 0}
            onChange={(value) => {
                if (value !== null) {
                    updateCurrentTeam({ week_start_day: value })
                }
            }}
            loading={currentTeamLoading}
            options={[
                { value: 0, label: 'Sunday' },
                { value: 1, label: 'Monday' },
            ]}
        />
    )
}
