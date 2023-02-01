import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/v1/ingestionLogic'
import { LemonButton, LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'
import { teamLogic } from 'scenes/teamLogic'
import { SupportHeroHog } from 'lib/components/hedgehogs'
import { useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function SuperpowersPanel(): JSX.Element {
    const { setVerify } = useActions(ingestionLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [sessionRecordingsChecked, setSessionRecordingsChecked] = useState(true)

    return (
        <div style={{ maxWidth: 800 }}>
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
                        updateCurrentTeam({
                            session_recording_opt_in: checked,
                            capture_console_log_opt_in: checked,
                            capture_performance_opt_in: checked,
                        })
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
                <Tooltip title="Autocapture can be disabled by customizing your JS snippet." placement="topRight">
                    <div className="flex justify-between w-full">
                        <p className="text-base font-semibold m-0">Autocapture frontend interactions</p>
                        <LemonSwitch data-attr="opt-in-autocapture-switch" checked={true} disabled={true} />
                    </div>
                </Tooltip>
                <p className="prompt-text ml-0">
                    If you use our JavaScript or React Native libraries, we'll automagically capture frontend
                    interactions like pageviews, clicks, and more.{' '}
                    <Link to={'https://posthog.com/docs/integrate/client/js#autocapture'} target="blank">
                        Fine-tune what you capture
                    </Link>{' '}
                    directly in your code snippet.
                </p>
            </div>

            <LemonDivider thick dashed className="my-6" />
            <div>
                <LemonButton
                    type="primary"
                    size="large"
                    fullWidth
                    center
                    className="mb-2"
                    onClick={() => {
                        // If they haven't changed the default value, we need to update the team with that value
                        updateCurrentTeam({
                            session_recording_opt_in: sessionRecordingsChecked,
                            capture_console_log_opt_in: sessionRecordingsChecked,
                            capture_performance_opt_in: sessionRecordingsChecked,
                        })
                        setVerify(true)
                    }}
                >
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}
