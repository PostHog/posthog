import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsMoEngageInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://www.moengage.com/" target="_blank">
                    MoEngage
                </Link>{' '}
                is a customer engagement platform. You can send your MoEngage data to PostHog for analysis using their
                PostHog integration.
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    Follow the{' '}
                    <Link
                        to="https://posthog.com/docs/libraries/moengage"
                        target="_blank"
                        targetBlankIcon
                        disableDocsPanel
                    >
                        MoEngage PostHog integration guide
                    </Link>{' '}
                    to set up the connection.
                </li>
                <li>
                    When prompted, enter your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Enter your PostHog host:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>Configure which MoEngage events and user data you want to sync to PostHog.</li>
            </ol>
            <p>
                Once configured, MoEngage will send event data to PostHog, allowing you to analyze customer engagement
                alongside your other product analytics data.
            </p>
        </>
    )
}
