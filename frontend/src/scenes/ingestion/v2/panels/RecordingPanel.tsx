import { SessionRecordingSettings } from 'scenes/session-recordings/settings/SessionRecordingSettings'
import { Link } from '@posthog/lemon-ui'
import { CardContainer } from 'scenes/ingestion/v2/CardContainer'

export function RecordingPanel(): JSX.Element {
    return (
        <CardContainer nextProps={{ readyToVerify: true }}>
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
        </CardContainer>
    )
}
