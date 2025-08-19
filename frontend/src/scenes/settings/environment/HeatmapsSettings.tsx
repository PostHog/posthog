import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

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
                If you use our JavaScript libraries, we can capture general clicks, mouse movements, and scrolling to
                create heatmaps. No additional events are created, and you can disable this at any time.
                <br />
                Whereas Autocapture creates events whenever it can uniquely identify an interacted element, heatmaps are
                generated based on overall mouse or touch positions and are useful for understanding more general user
                behavior across your site.
            </p>
            <div className="deprecated-space-y-2">
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
