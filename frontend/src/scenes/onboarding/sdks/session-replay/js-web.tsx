import { JSSnippet } from 'lib/components/JSSnippet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { JSInstallSnippet, SessionReplayFinalSteps } from '../shared-snippets'

function JSSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.JavaScript}>
            {[
                "import posthog from 'posthog-js'",
                '',
                `posthog.init('${currentTeam?.api_token}', { api_host: '${window.location.origin}' })`,
            ].join('\n')}
        </CodeSnippet>
    )
}

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <h3>Option 1. Code snippet</h3>
            <p>
                Just add this snippet to your website within the <code>&lt;head&gt;</code> tag and we'll automatically
                capture page views, sessions and all relevant interactions within your website.
            </p>
            <JSSnippet />
            <LemonDivider thick dashed className="my-4" />
            <h3>Option 2. Javascript Library</h3>
            <h4>Install the package</h4>
            <JSInstallSnippet />
            <h4>Initialize</h4>
            <JSSetupSnippet />
            <LemonDivider thick dashed className="my-4" />
            <h3>Final steps</h3>
            <SessionReplayFinalSteps />
        </>
    )
}
