import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsLangfuseInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://langfuse.com/" target="_blank">
                    Langfuse
                </Link>{' '}
                supports most popular LLM models and you can bring your Langfuse data into PostHog for analysis. To get
                started:
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    First add{' '}
                    <Link to="https://langfuse.com/docs/tracing" target="_blank">
                        Langfuse Tracing
                    </Link>{' '}
                    to your LLM app.
                </li>
                <li>
                    In your{' '}
                    <Link to="https://cloud.langfuse.com/" target="_blank">
                        Langfuse dashboard
                    </Link>
                    , click on <strong>Settings</strong> and scroll down to the <strong>Integrations</strong> section to
                    find the PostHog integration.
                </li>
                <li>
                    Click <strong>Configure</strong> and paste in your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Paste in your PostHog host:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>
                    Click <strong>Enable</strong> and then <strong>Save</strong>.
                </li>
            </ol>
            <p>
                Langfuse will now begin exporting your data into PostHog. Note that Langfuse batch exports your data
                into PostHog once a day, so it can take up to 24 hours for your Langfuse data to appear in PostHog.
            </p>
        </>
    )
}
