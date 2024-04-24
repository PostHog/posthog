import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function HeatmapsSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportHeatmapsToggled } = useActions(eventUsageLogic)

    return (
        <>
            <p>
                If heatmaps are enabled, PostHog will automatically capture clicks, mouse movements, and scrolls to
                generate heatmaps.
                <br />
                Whereas heatmaps creates events whenever it can uniquely identify an interacted element, heatmaps are
                generated based on general mouse positions and are useful for understanding getting behavior.
            </p>
            <div className="space-y-2">
                <LemonSwitch
                    id="posthog-heatmaps-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            heatmaps_opt_in: checked,
                        })
                        reportHeatmapsToggled(checked)
                    }}
                    checked={!!currentTeam?.heatmaps_opt_in}
                    disabled={userLoading}
                    label="Enable heatmaps for web"
                    bordered
                />
            </div>
        </>
    )
}
