import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { useActions, useValues } from 'kea'
import { SupportHeroHog } from 'lib/components/hedgehogs'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { ingestionLogic } from '../ingestionLogic'

export function SuperpowersPanel(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { showBillingStep } = useValues(ingestionLogic)
    const { completeOnboarding } = useActions(ingestionLogic)
    const [sessionRecordingsChecked, setSessionRecordingsChecked] = useState(true)
    const [autocaptureChecked, setAutocaptureChecked] = useState(true)
    const [surveysChecked, setSurveysChecked] = useState(true)

    return (
        <CardContainer
            nextProps={{ showBilling: showBillingStep }}
            onContinue={() => {
                updateCurrentTeam({
                    session_recording_opt_in: sessionRecordingsChecked,
                    capture_console_log_opt_in: sessionRecordingsChecked,
                    capture_performance_opt_in: sessionRecordingsChecked,
                    autocapture_opt_out: !autocaptureChecked,
                    surveys_opt_in: surveysChecked,
                })
                if (!showBillingStep) {
                    completeOnboarding()
                }
            }}
            finalStep={!showBillingStep}
        >
            <div className="flex justify-between items-center -mt-4">
                <div>
                    <h1 className="font-extrabold pt-4">Enable your product superpowers</h1>
                    <p className="m-0">
                        Collecting events from your app is just the first step toward building great products. PostHog
                        gives you other superpowers, too, like recording user sessions and automagically capturing
                        frontend interactions.
                    </p>
                </div>
                <div className="ml-8">
                    <SupportHeroHog className="w-full h-full" />
                </div>
            </div>
            <div className="my-8">
                <LemonSwitch
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        setSessionRecordingsChecked(checked)
                    }}
                    label="Record user sessions"
                    fullWidth={true}
                    labelClassName={'text-base font-semibold'}
                    checked={sessionRecordingsChecked}
                />
                <p className="prompt-text ml-0">
                    See recordings of how your users are really using your product with powerful features like error
                    tracking, filtering, and analytics.{' '}
                    <Link to={'https://posthog.com/manual/recordings'} target="blank">
                        Learn more
                    </Link>{' '}
                    about Session recordings.
                </p>
            </div>
            <div>
                <LemonSwitch
                    data-attr="opt-in-autocapture-switch"
                    onChange={(checked) => {
                        setAutocaptureChecked(checked)
                    }}
                    label="Autocapture frontend interactions"
                    fullWidth={true}
                    labelClassName={'text-base font-semibold'}
                    checked={autocaptureChecked}
                />
                <p className="prompt-text ml-0">
                    If you use our JavaScript or React Native libraries, we'll automagically capture frontend
                    interactions like pageviews, clicks, and more.{' '}
                    <Link to={'https://posthog.com/docs/integrate/client/js#autocapture'} target="blank">
                        Fine-tune what you capture
                    </Link>{' '}
                    directly in your code snippet.
                </p>
            </div>
            <div>
                <LemonSwitch
                    data-attr="opt-in-surveys-switch"
                    onChange={(checked) => {
                        setSurveysChecked(checked)
                    }}
                    label="Get qualitative feedback from your users"
                    fullWidth={true}
                    labelClassName={'text-base font-semibold'}
                    checked={surveysChecked}
                />
                <p className="prompt-text ml-0">
                    Collect feedback from your users directly in your product.{' '}
                    <Link to={'https://posthog.com/docs/surveys'} target="blank">
                        Learn more
                    </Link>{' '}
                    about Surveys.
                </p>
            </div>
        </CardContainer>
    )
}
