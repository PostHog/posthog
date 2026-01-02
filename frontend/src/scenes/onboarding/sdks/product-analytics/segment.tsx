import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsSegmentInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://segment.com/" target="_blank">
                    Segment
                </Link>{' '}
                is a customer data platform that can route your analytics data to PostHog and other destinations.
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    In your Segment workspace, go to <strong>Connections</strong> → <strong>Catalog</strong> and search
                    for <strong>PostHog</strong>.
                </li>
                <li>
                    Click <strong>Add Destination</strong> and select the source you want to connect.
                </li>
                <li>
                    Enter your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Enter your PostHog host:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>Enable the destination.</li>
            </ol>
            <p>
                Segment will now forward <code>track</code>, <code>identify</code>, <code>page</code>, and{' '}
                <code>group</code> calls to PostHog. See the{' '}
                <Link to="https://posthog.com/docs/libraries/segment" target="_blank" targetBlankIcon disableDocsPanel>
                    Segment integration docs
                </Link>{' '}
                for more details.
            </p>
        </>
    )
}
