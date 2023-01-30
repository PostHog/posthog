import { SessionRecordingSettings } from 'scenes/session-recordings/settings/SessionRecordingSettings'
import { Link } from 'lib/components/Link'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonButton } from 'lib/components/LemonButton'
import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/v1/ingestionLogic'

export function RecordingPanel(): JSX.Element {
    const { setVerify } = useActions(ingestionLogic)

    return (
        <div style={{ maxWidth: 800 }}>
            <h1 className="font-extrabold">Setup Session Recordings</h1>
            <p className="prompt-text">
                Session recordings allow you to see recordings of how your users are really using your product. It
                includes powerful features like error tracking, filtering, and analytics to <b>diagnose UI issues</b>,{' '}
                <b>improve support</b>, and <b>generally get inspired</b>.
            </p>
            <p>
                No further configuration is required to immediately start capturing recordings. Learn more about
                specific recordings settings in our{' '}
                <Link to="https://posthog.com/manual/recordings#using-session-recording" target="_blank">
                    docs
                </Link>
                .
            </p>

            <SessionRecordingSettings inModal />
            <LemonDivider thick dashed className="my-6" />
            <div>
                <LemonButton
                    type="primary"
                    size="large"
                    fullWidth
                    center
                    className="mb-2"
                    onClick={() => setVerify(true)}
                >
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}
