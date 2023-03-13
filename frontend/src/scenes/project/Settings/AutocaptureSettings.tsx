import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function AutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportIngestionAutocaptureToggled } = useActions(eventUsageLogic)

    return (
        <>
            <h2 className="subtitle">Autocapture</h2>
            <p>
                Automagically capture frontend interactions like pageviews, clicks, and more when using our JavaScript
                or React Native libraries.
            </p>
            <LemonSwitch
                id="posthog-autocapture-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        autocapture_opt_out: !checked,
                    })
                    reportIngestionAutocaptureToggled(!checked)
                }}
                checked={!currentTeam?.autocapture_opt_out}
                disabled={userLoading}
                label="Enable Autocapture"
                bordered
            />
        </>
    )
}
