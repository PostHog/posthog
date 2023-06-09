import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

export function AutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportIngestionAutocaptureToggled, reportIngestionAutocaptureExceptionsToggled } =
        useActions(eventUsageLogic)

    return (
        <>
            <h2 className="subtitle">Autocapture</h2>
            <p>
                Automagically capture frontend interactions like pageviews, clicks, and more when using our JavaScript
                or React Native libraries.
            </p>
            <div className="space-y-2">
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
                <FlaggedFeature flag={FEATURE_FLAGS.EXCEPTION_AUTOCAPTURE} match={true}>
                    <LemonSwitch
                        id="posthog-autocapture-exceptions-switch"
                        onChange={(checked) => {
                            updateCurrentTeam({
                                autocapture_exceptions_opt_in: checked,
                            })
                            reportIngestionAutocaptureExceptionsToggled(checked)
                        }}
                        checked={!!currentTeam?.autocapture_exceptions_opt_in}
                        disabled={userLoading}
                        label={
                            <>
                                Enable Exception Autocapture <LemonTag>ALPHA</LemonTag>
                            </>
                        }
                        bordered
                    />
                </FlaggedFeature>
            </div>
        </>
    )
}
