import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch, LemonTag, LemonTextArea } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import clsx from 'clsx'
import { autocaptureExceptionsLogic } from 'scenes/project/Settings/autocaptureExceptionsLogic'

export function AutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportIngestionAutocaptureToggled, reportIngestionAutocaptureExceptionsToggled } =
        useActions(eventUsageLogic)

    const { errorsToDropRules, rulesCharacters } = useValues(autocaptureExceptionsLogic)
    const { setErrorsToDropRules } = useActions(autocaptureExceptionsLogic)

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
                    <div className={'mt-4 border rounded px-6 py-4'}>
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
                        <h2 className="subtitle">Drop errors</h2>
                        <p>
                            If you're experiencing a high volume of errors, you can drop them to reduce the load on your
                            PostHog instance. This will drop all errors that match, including those that are not
                            autocaptured.
                            <br />
                            You can enter error titles here to drop them. One per line. For example, if you want to drop
                            all errors that contain the word "bot", you can enter "*bot*" here.
                            <br />
                            Only up to 300 characters of config are allowed here. More than that and you must initialize
                            this setting directly in posthog-js.
                        </p>
                        <LemonTextArea
                            id="posthog-autocapture-exceptions-dropped"
                            value={errorsToDropRules}
                            onChange={setErrorsToDropRules}
                            disabled={!currentTeam?.autocapture_exceptions_opt_in}
                        />
                        <div
                            className={clsx(
                                'mt-2 text-xs text-right',
                                rulesCharacters > 300 ? 'text-danger' : 'text-muted'
                            )}
                        >
                            {rulesCharacters} / 300 characters
                        </div>
                    </div>
                </FlaggedFeature>
            </div>
        </>
    )
}
