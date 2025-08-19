import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsTraceloopInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://www.traceloop.com/" target="_blank">
                    Traceloop
                </Link>{' '}
                supports most popular LLM models and you can bring your Traceloop data into PostHog for analysis. To get
                started:
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    Go to the{' '}
                    <Link to="https://app.traceloop.com/settings/integrations" target="_blank">
                        integrations page
                    </Link>{' '}
                    in your Traceloop dashboard and click on the PostHog card.
                </li>
                <li>
                    Paste in your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Paste in your PostHog host:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>
                    Select the environment you want to connect to PostHog and click <strong>Enable</strong>
                </li>
            </ol>
            <p>Traceloop events will now be exported into PostHog as soon as they're available.</p>
        </>
    )
}
