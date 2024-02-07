import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

function PythonInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>pip install posthog</CodeSnippet>
}

function PythonSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Python}>
            {`from posthog import Posthog

posthog = Posthog(project_api_key='${currentTeam?.api_token}', host='${apiHostOrigin()}')

            `}
        </CodeSnippet>
    )
}

export function SDKInstallPythonInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <PythonInstallSnippet />
            <h3>Configure</h3>
            <PythonSetupSnippet />
        </>
    )
}
