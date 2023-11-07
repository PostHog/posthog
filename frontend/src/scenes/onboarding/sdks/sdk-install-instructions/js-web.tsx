import { JSSnippet } from 'lib/components/JSSnippet'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

export function JSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {['npm install posthog-js', '# OR', 'yarn add posthog-js', '# OR', 'pnpm add posthog-js'].join('\n')}
        </CodeSnippet>
    )
}

export function JSSetupSnippet(): JSX.Element {
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

export function SDKInstallJSWebInstructions(): JSX.Element {
    return (
        <>
            <h3>Option 1. Code snippet</h3>
            <p>
                Just add this snippet to your website within the <code>&lt;head&gt;</code> tag and you'll be ready to
                start using PostHog.{' '}
            </p>
            <JSSnippet />
            <LemonDivider thick dashed className="my-4" />
            <h3>Option 2. Javascript Library</h3>
            <h4>Install the package</h4>
            <JSInstallSnippet />
            <h4>Initialize</h4>
            <JSSetupSnippet />
        </>
    )
}
