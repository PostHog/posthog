import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsZapierInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://zapier.com/apps/posthog/integrations" target="_blank">
                    Zapier
                </Link>{' '}
                lets you connect PostHog to thousands of other apps. You can use it to send events to PostHog from other
                services or trigger actions based on PostHog events.
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    Go to the{' '}
                    <Link to="https://zapier.com/apps/posthog/integrations" target="_blank">
                        PostHog integration page
                    </Link>{' '}
                    on Zapier and click <strong>Connect PostHog</strong>.
                </li>
                <li>
                    When prompted, enter your PostHog project API key:
                    <CodeSnippet language={Language.JavaScript}>{currentTeam?.api_token}</CodeSnippet>
                </li>
                <li>
                    Enter your PostHog host:
                    <CodeSnippet language={Language.JavaScript}>{apiHostOrigin()}</CodeSnippet>
                </li>
                <li>Create a Zap that sends events to PostHog using the "Capture Event" action.</li>
            </ol>
            <p>
                Events captured via Zapier will appear in PostHog just like events from any other source. You can use
                Zapier to connect CRMs, payment processors, customer support tools, and more.
            </p>
        </>
    )
}
