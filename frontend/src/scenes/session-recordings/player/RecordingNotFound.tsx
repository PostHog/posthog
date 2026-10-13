import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { ReplayCaptureDiagnosticsPanel } from 'scenes/session-recordings/components/ReplayCaptureDiagnosticsPanel'
import { ReplayStatusBanner } from 'scenes/session-recordings/player/ReplayStatusBanner'

export function RecordingNotFound({ sessionRecordingId }: { sessionRecordingId?: string }): JSX.Element {
    return (
        <div className="flex flex-col items-center w-full overflow-y-auto">
            <NotFound
                object="Recording"
                className="shrink-0"
                style={sessionRecordingId ? { marginBottom: 0 } : undefined}
                caption={
                    <>
                        The requested recording could not be found. See the diagnosis below for likely reasons, or refer
                        to the{' '}
                        <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                            troubleshooting guide
                        </Link>
                        .
                        <ReplayStatusBanner />
                    </>
                }
            />
            {sessionRecordingId && (
                <div className="mt-4 mb-12 w-full max-w-xl shrink-0 px-4">
                    <ReplayCaptureDiagnosticsPanel sessionId={sessionRecordingId} />
                </div>
            )}
        </div>
    )
}
