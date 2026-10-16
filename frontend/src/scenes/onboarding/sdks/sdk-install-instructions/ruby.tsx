import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

function RubyInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>gem "posthog-ruby"</CodeSnippet>
}

function RubySetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Ruby}>
            {`posthog = PostHog::Client.new({
    api_key: "${currentTeam?.api_token}",
    host: "${apiHostOrigin()}",
    on_error: Proc.new { |status, msg| print msg }
})`}
        </CodeSnippet>
    )
}

export function SDKInstallRubyInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <RubyInstallSnippet />
            <h3>Configure</h3>
            <RubySetupSnippet />
        </>
    )
}
