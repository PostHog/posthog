import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
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

export function JSInstructions(): JSX.Element {
    return (
        <div>
            <b>Steps:</b>
            <ol>
                <li>
                    Install the package <JSInstallSnippet />
                </li>
                <li>
                    Configure &amp; initialize (see more{' '}
                    <Link
                        to="https://posthog.com/docs/integrations/js-integration#config"
                        target="_blank"
                        rel="noopener"
                    >
                        configuration options
                    </Link>
                    ) <JSSetupSnippet />
                </li>
                <li>
                    Send your first event <JSEventSnippet />
                </li>
            </ol>
        </div>
    )
}
