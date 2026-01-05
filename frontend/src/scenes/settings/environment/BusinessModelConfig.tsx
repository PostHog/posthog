import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

export function BusinessModelConfig(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <LemonSelect
            value={currentTeam?.business_model || null}
            onChange={(value) => updateCurrentTeam({ business_model: value })}
            disabledReason={currentTeamLoading ? 'Loading...' : undefined}
            fullWidth
            className="max-w-160"
            options={[
                { value: null, label: 'Not specified' },
                { value: 'b2b', label: 'B2B' },
                { value: 'b2c', label: 'B2C' },
                { value: 'other', label: 'Other' },
            ]}
        />
    )
}
