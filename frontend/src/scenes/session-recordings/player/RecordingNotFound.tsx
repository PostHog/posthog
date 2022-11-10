import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { NotFound } from 'lib/components/NotFound'

export function RecordingNotFound(): JSX.Element {
    return (
        <NotFound
            object={'Recording'}
            caption={
                <>
                    The requested recording doesn't seem to exist. The recording may still be processing, deleted due to
                    age or have not been enabled. Please check your{' '}
                    <Link to={urls.projectSettings()}>project settings</Link> that recordings is turned on and enabled
                    for the domain in question.
                </>
            }
        />
    )
}
