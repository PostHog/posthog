import { Link } from '@posthog/lemon-ui'
import { CodeSnippet } from 'lib/components/CodeSnippet'

export function SessionReplayFinalSteps(): JSX.Element {
    return (
        <>
            <h3>Create a recording</h3>
            <p>Visit your site and click around to generate an initial recording.</p>
        </>
    )
}

export function PersonModeEventPropertyInstructions(): JSX.Element {
    return (
        <>
            <h4>Optional: Specify person profile processing</h4>
            <p>
                By default, for backwards compatibility reasons, events are sent with{' '}
                <Link to="https://posthog.com/docs/data/persons" target="_blank" targetBlankIcon>
                    person profile processing
                </Link>{' '}
                enabled. This means a person profile will be created for each user who triggers an event.
            </p>
            <p>
                If you want to disable person profile processing for certain events, send the event with the following
                property:
            </p>
            <CodeSnippet>"$process_person_profile": false</CodeSnippet>.
        </>
    )
}
