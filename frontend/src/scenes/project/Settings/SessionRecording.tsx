import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { SessionRecordingSettings } from 'scenes/session-recordings/settings/SessionRecordingSettings'

export function SessionRecording(): JSX.Element {
    return (
        <>
            <h2 id="recordings" className="subtitle">
                Recordings
            </h2>
            <p>
                Watch recordings of how users interact with your web app to see what can be improved. Recordings are
                found in the <Link to={urls.sessionRecordings()}>recordings page</Link>.
            </p>

            <SessionRecordingSettings />
        </>
    )
}
