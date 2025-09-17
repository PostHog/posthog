import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function DeadClicksAutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <>
            <p>
                A dead click is a click that doesn't result in any action. E.g. an image that looks like a button. Your
                user clicks it, nothing happens, they get frustrated and close the tab, and you missed a sale.
            </p>
            <p>
                We track clicks that aren't followed by a scroll, text selection change, or DOM mutation and report them
                so you can see where your users are getting stuck.
            </p>
            <div className="deprecated-space-y-2">
                <LemonSwitch
                    id="posthog-deadclicks-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            capture_dead_clicks: checked,
                        })
                        posthog.capture('dead_clicks_autocapture_toggled', { isEnabled: checked })
                    }}
                    checked={!!currentTeam?.capture_dead_clicks}
                    disabled={userLoading}
                    label="Enable dead clicks autocapture"
                    bordered
                />
            </div>
        </>
    )
}
