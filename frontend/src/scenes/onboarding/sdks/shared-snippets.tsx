import { Link } from 'lib/lemon-ui/Link'

export function SessionReplayFinalSteps(): JSX.Element {
    return (
        <>
            <h3>Optional: Configure</h3>
            <p>
                Advanced users can add{' '}
                <Link to="https://posthog.com/docs/libraries/js#config" target="_blank">
                    configuration options
                </Link>{' '}
                to customize text masking, customize or disable event capturing, and more.
            </p>
            <h3>Create a recording</h3>
            <p>Visit your site and click around to generate an initial recording.</p>
        </>
    )
}
