import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

function PHPInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>composer require posthog/posthog-php</CodeSnippet>
}

function PHPSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.PHP}>
            {`PostHog\\PostHog::init('${currentTeam?.api_token}',
    array('host' => '${apiHostOrigin()}')
);`}
        </CodeSnippet>
    )
}

export function SDKInstallPHPInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <PHPInstallSnippet />
            <h3>Configure</h3>
            <PHPSetupSnippet />
        </>
    )
}
