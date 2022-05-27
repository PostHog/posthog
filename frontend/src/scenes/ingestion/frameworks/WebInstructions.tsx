import React from 'react'
import { Link } from 'lib/components/Link'
import { JSSnippet } from 'lib/components/JSSnippet'
import { LemonDivider } from 'lib/components/LemonDivider'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function JSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {['npm install posthog-js', '# OR', 'yarn add posthog-js'].join('\n')}
        </CodeSnippet>
    )
}

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

function JSEventSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>{`posthog.capture('my event', { property: 'value' })`}</CodeSnippet>
    )
}

export function WebInstructions(): JSX.Element {
    return (
        <>
            <h1>Connect your web app or product</h1>
            <div style={{ display: 'flex', alignItems: 'center' }}>
                <h2>Option 1. Code snippet</h2>
                <div
                    style={{
                        marginLeft: 10,
                        padding: 4,
                        backgroundColor: '#fdedc9',
                        borderRadius: 'var(--radius)',
                        color: 'var(--primary-alt)',
                        fontSize: 11,
                        fontWeight: 600,
                        letterSpacing: '0.02em',
                        textAlign: 'center',
                    }}
                    color="orange"
                >
                    Recommended
                </div>
            </div>
            <p>
                Just add this snippet to your website and we'll automatically capture page views, sessions and all
                relevant interactions within your website.{' '}
                <Link
                    to="https://posthog.com/product-features/event-autocapture?utm_medium=in-product&utm_campaign=ingestion-web"
                    target="_blank"
                    rel="noopener"
                >
                    Learn more
                </Link>
                .
            </p>
            <h3>Install the snippet</h3>
            <p>
                Insert this snippet in your website within the <code className="code">&lt;head&gt;</code> tag.{' '}
                <JSSnippet />
            </p>
            <h3>Send events </h3>
            <p>Visit your site and click around to generate some initial events.</p>
            <LemonDivider thick dashed />
            <h2>Option 2. Javascript Library</h2>
            <p>
                Use this option if you want more granular control of how PostHog runs in your website and the events you
                capture. Recommended for teams with more stable products and more defined analytics requirements.{' '}
                <Link
                    to="https://posthog.com/docs/integrations/js-integration/?utm_medium=in-product&utm_campaign=ingestion-web"
                    target="_blank"
                    rel="noopener"
                >
                    Learn more
                </Link>
                .
            </p>
            <h3>Install the package</h3>
            <JSInstallSnippet />
            <h3>
                Configure &amp; initialize (see more{' '}
                <Link to="https://posthog.com/docs/integrations/js-integration#config" target="_blank" rel="noopener">
                    configuration options
                </Link>
                )
            </h3>
            <JSSetupSnippet />
            <h3>Send your first event</h3>
            <JSEventSnippet />
        </>
    )
}
