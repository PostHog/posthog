import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsSentryInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                <Link to="https://sentry.io/" target="_blank">
                    Sentry
                </Link>{' '}
                is an error tracking platform. The PostHog-Sentry integration links error data to your analytics,
                allowing you to see which users experienced errors.
            </p>
            <h4>Install the integration</h4>
            <CodeSnippet language={Language.Bash}>npm install --save posthog-js @sentry/browser</CodeSnippet>
            <h4>Configure</h4>
            <p>Add the Sentry integration when initializing PostHog:</p>
            <CodeSnippet language={Language.JavaScript}>
                {`import posthog from 'posthog-js'
import * as Sentry from '@sentry/browser'

// Initialize Sentry first
Sentry.init({
  dsn: 'your-sentry-dsn',
})

// Initialize PostHog with Sentry integration
posthog.init('${currentTeam?.api_token}', {
  api_host: '${apiHostOrigin()}',
  // Link PostHog session to Sentry errors
  on_xhr_error: (err) => {
    Sentry.captureException(err)
  },
})

// Set PostHog session ID on Sentry scope
Sentry.getCurrentScope().setTag('posthog_session_id', posthog.get_session_id())`}
            </CodeSnippet>
            <p>
                This allows you to link Sentry errors to PostHog sessions and see which users experienced errors. See
                the{' '}
                <Link to="https://posthog.com/docs/libraries/sentry" target="_blank" targetBlankIcon disableDocsPanel>
                    Sentry integration docs
                </Link>{' '}
                for the full setup guide.
            </p>
        </>
    )
}
