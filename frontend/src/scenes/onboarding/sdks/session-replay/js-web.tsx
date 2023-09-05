import { Link } from 'lib/lemon-ui/Link'
import { JSSnippet } from 'lib/components/JSSnippet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function JSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {['npm install posthog-js', '# OR', 'yarn add posthog-js', '# OR', 'pnpm add posthog-js'].join('\n')}
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

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <h3>Option 1. Code snippet</h3>
            <p>
                Just add this snippet to your website and we'll automatically capture page views, sessions and all
                relevant interactions within your website.
            </p>
            <h4>Install the snippet</h4>
            <p>
                Insert this snippet in your website within the <code>&lt;head&gt;</code> tag.
            </p>
            <JSSnippet />
            <LemonDivider thick dashed className="my-4" />
            <h3>Option 2. Javascript Library</h3>
            <p>
                Use this option if you want more granular control of how PostHog runs in your website and the events you
                capture. Recommended for teams with more stable products and more defined analytics requirements.{' '}
                <Link
                    to="https://posthog.com/docs/integrate/client/js/?utm_medium=in-product&utm_campaign=ingestion-web"
                    target="_blank"
                >
                    Learn more
                </Link>
                .
            </p>
            <h4>Install the package</h4>
            <JSInstallSnippet />
            <h4>
                Configure &amp; initialize (see more{' '}
                <Link to="https://posthog.com/docs/integrations/js-integration#config" target="_blank">
                    configuration options
                </Link>
                )
            </h4>
            <JSSetupSnippet />
            <h4>Create a recording</h4>
            <p>Visit your site and click around to generate an initial recording.</p>
        </>
    )
}
