import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { Link } from 'lib/components/Link'

function JSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {['npm install posthog-js', '# OR', 'yarn add posthog-js'].join('\n')}
        </CodeSnippet>
    )
}

function JSSetupSnippet(): JSX.Element {
    const { user } = useValues(userLogic)
    return (
        <CodeSnippet language={Language.JavaScript}>
            {[
                "import posthog from 'posthog-js'",
                '',
                `posthog.init('${user?.team?.api_token}', { api_host: '${window.location.origin}' })`,
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
