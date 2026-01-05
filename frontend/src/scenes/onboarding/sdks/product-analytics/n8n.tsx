import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsN8nInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://n8n.io/" target="_blank">
                    n8n
                </Link>{' '}
                is an open-source workflow automation tool. You can use the PostHog node to send events from your n8n
                workflows to PostHog.
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    In your n8n workflow, add the{' '}
                    <Link
                        to="https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.posthog/"
                        target="_blank"
                    >
                        PostHog node
                    </Link>
                    .
                </li>
                <li>
                    Create credentials with your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Set the PostHog host URL:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>
                    Configure the node to capture events, identify users, or create aliases based on your workflow
                    needs.
                </li>
            </ol>
            <p>
                Events from n8n will appear in PostHog just like events from any other source. This is great for
                connecting backend systems, databases, and third-party APIs to your analytics.
            </p>
        </>
    )
}
