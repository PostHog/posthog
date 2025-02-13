import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

export function IPCapture(): JSX.Element {
    const { updateCurrentTeamConfig } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <LemonSwitch
            onChange={(checked) => {
                updateCurrentTeamConfig({ anonymize_ips: checked })
            }}
            checked={!!currentTeam?.anonymize_ips}
            disabled={currentTeamLoading}
            label="Discard client IP data"
            bordered
        />
    )
}
