import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'

export function WeekStartConfig(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <LemonSelect
            value={currentTeam?.week_start_day || 0}
            onChange={(value) => {
                LemonDialog.open({
                    title: `Change the first day of the week to ${value === 0 ? 'Sunday' : 'Monday'}?`,
                    description: 'Queries grouped by week will need to be recalculated.',
                    primaryButton: {
                        children: 'Change week definition',
                        onClick: () => updateCurrentTeam({ week_start_day: value }),
                    },
                    secondaryButton: {
                        children: 'Cancel',
                    },
                })
            }}
            loading={currentTeamLoading}
            options={[
                { value: 0, label: 'Sunday' },
                { value: 1, label: 'Monday' },
            ]}
        />
    )
}
