import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch } from '@posthog/lemon-ui'

export function IPCapture(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <LemonSwitch
            onChange={(checked) => {
                updateCurrentTeam({ anonymize_ips: checked })
            }}
            checked={!!currentTeam?.anonymize_ips}
            disabled={currentTeamLoading}
            label="Discard client IP data"
            bordered
        />
    )
}
