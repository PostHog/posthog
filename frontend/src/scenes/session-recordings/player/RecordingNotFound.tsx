import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function RecordingNotFound(): JSX.Element {
    return (
        <NotFound
            object="Recording"
            caption={
                <>
                    The requested recording doesn't seem to exist. The recording may still be processing, deleted due to
                    age or have not been enabled. Please check your{' '}
                    <Link to={urls.settings('project')}>project settings</Link> that recordings is turned on and enabled
                    for the domain in question. Alternatively read the{' '}
                    <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                        troubleshooting guide
                    </Link>
                    .
                </>
            }
        />
    )
}
