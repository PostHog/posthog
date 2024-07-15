import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
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
            <ol className="space-y-4">
                <li>
                    Go to the{' '}
                    <Link to="https://app.traceloop.com/settings/integrations" target="_blank">
                        integrations page
                    </Link>{' '}
                    in your Traceloop dashboard and click on the PostHog card.
                </li>
                <li>
                    Enter in your PostHog host and project API key:
                    <CodeSnippet language={Language.JavaScript}>
                        {`${currentTeam?.api_token} // your api key
${apiHostOrigin()} // your host`}
                    </CodeSnippet>
                </li>
                <li>
                    Select the environment you want to connect to PostHog and click <strong>Enable</strong>
                </li>
            </ol>
            <p>Traceloop events will now be exported into PostHog as soon as they're available.</p>
        </>
    )
}
