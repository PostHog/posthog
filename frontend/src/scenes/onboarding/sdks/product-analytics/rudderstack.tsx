import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsRudderstackInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://www.rudderstack.com/" target="_blank">
                    RudderStack
                </Link>{' '}
                is an open-source customer data platform that can route your analytics data to PostHog and other
                destinations.
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    In your RudderStack dashboard, go to <strong>Destinations</strong> and click{' '}
                    <strong>Add Destination</strong>.
                </li>
                <li>
                    Search for <strong>PostHog</strong> and select it.
                </li>
                <li>
                    Enter your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Enter your PostHog host:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>Connect your source to the PostHog destination.</li>
            </ol>
            <p>
                RudderStack will now forward <code>track</code>, <code>identify</code>, <code>page</code>, and{' '}
                <code>group</code> calls to PostHog. See the{' '}
                <Link
                    to="https://posthog.com/docs/libraries/rudderstack"
                    target="_blank"
                    targetBlankIcon
                    disableDocsPanel
                >
                    RudderStack integration docs
                </Link>{' '}
                for more details.
            </p>
        </>
    )
}
