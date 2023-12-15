import { LemonSwitch, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { autocaptureExceptionsLogic } from './autocaptureExceptionsLogic'

export function AutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportAutocaptureToggled } = useActions(eventUsageLogic)

    return (
        <>
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
                        reportAutocaptureToggled(!checked)
                    }}
                    checked={!currentTeam?.autocapture_opt_out}
                    disabled={userLoading}
                    label="Enable autocapture for web"
                    bordered
                />
            </div>
        </>
    )
}

export function ExceptionAutocaptureSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)

    const { errorsToIgnoreRules, rulesCharacters } = useValues(autocaptureExceptionsLogic)
    const { setErrorsToIgnoreRules } = useActions(autocaptureExceptionsLogic)

    return (
        <>
            <LemonSwitch
                id="posthog-autocapture-exceptions-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        autocapture_exceptions_opt_in: checked,
                    })
                    reportAutocaptureExceptionsToggled(checked)
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
            <h3 className="mt-4">Ignore errors</h3>
            <p>
                If you're experiencing a high volume of unhelpful errors, add regular expressions here to ignore them.
                This will ignore all errors that match, including those that are not autocaptured.
            </p>
            <p>
                You can enter a regular expression that matches values of{' '}
                <PropertyKeyInfo value={'$exception_message'} /> here to ignore them. One per line. For example, if you
                want to drop all errors that contain the word "bot", you can enter "bot" here. Or if you want to drop
                all errors that are exactly "bot", you can enter "^bot$".
            </p>
            <p>Only up to 300 characters of config are allowed here.</p>
            <LemonTextArea
                id="posthog-autocapture-exceptions-dropped"
                value={errorsToIgnoreRules}
                onChange={setErrorsToIgnoreRules}
                disabled={!currentTeam?.autocapture_exceptions_opt_in}
            />
            <div className={clsx('mt-2 text-xs text-right', rulesCharacters > 300 ? 'text-danger' : 'text-muted')}>
                {rulesCharacters} / 300 characters
            </div>
        </>
    )
}
