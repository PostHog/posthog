import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonSwitch, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import clsx from 'clsx'
import { autocaptureExceptionsLogic } from 'scenes/project/Settings/autocaptureExceptionsLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function AutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportIngestionAutocaptureToggled, reportIngestionAutocaptureExceptionsToggled } =
        useActions(eventUsageLogic)

    const { errorsToIgnoreRules, rulesCharacters } = useValues(autocaptureExceptionsLogic)
    const { setErrorsToIgnoreRules } = useActions(autocaptureExceptionsLogic)

    return (
        <>
            <h2 className="subtitle">Autocapture</h2>
            <p>
                Automagically capture front-end interactions like pageviews, clicks, and more when using our web
                JavaScript SDK.{' '}
            </p>
            <p>
                Autocapture is also available for React Native, where it has to be{' '}
                <Link to="https://posthog.com/docs/libraries/react-native#autocapture" target="_blank">
                    configured directly in code
                </Link>
                .
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
                    label="Enable autocapture for web"
                    bordered
                />
                <FlaggedFeature flag={FEATURE_FLAGS.EXCEPTION_AUTOCAPTURE}>
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
                                    Enable exception autocapture <LemonTag>ALPHA</LemonTag>
                                </>
                            }
                            bordered
                        />
                        <h2 className="subtitle">Ignore errors</h2>
                        <p>
                            If you're experiencing a high volume of unhelpful errors, add regular expressions here to
                            ignore them. This will ignore all errors that match, including those that are not
                            autocaptured.
                        </p>
                        <p>
                            You can enter a regular expression that matches values of{' '}
                            <PropertyKeyInfo value={'$exception_message'} /> here to ignore them. One per line. For
                            example, if you want to drop all errors that contain the word "bot", or you can enter "bot"
                            here. Or if you want to drop all errors that are exactly "bot", you can enter "^bot$".
                        </p>
                        <p>Only up to 300 characters of config are allowed here.</p>
                        <LemonTextArea
                            id="posthog-autocapture-exceptions-dropped"
                            value={errorsToIgnoreRules}
                            onChange={setErrorsToIgnoreRules}
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
