import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

type PostHogPythonOptions = {
    enableExceptionAutocapture?: boolean
    djangoIntegration?: boolean
}

function PythonInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>pip install posthog</CodeSnippet>
}

export function PythonSetupSnippet({
    enableExceptionAutocapture = false,
    djangoIntegration = false,
}: PostHogPythonOptions): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const options = [`host='${apiHostOrigin()}'`]

    if (enableExceptionAutocapture) {
        options.push('enable_exception_autocapture=True')
    }
    if (djangoIntegration) {
        options.push('exception_autocapture_integrations = [Integrations.Django]')
    }

    return (
        <CodeSnippet language={Language.Python}>
            {`from posthog import Posthog
${djangoIntegration ? 'from posthog.integrations.django import Integrations\n' : ''}
posthog = Posthog(
  project_api_key='${currentTeam?.api_token}',
  ${options.join(',\n  ')}
)`}
        </CodeSnippet>
    )
}

export function SDKInstallPythonInstructions(props: PostHogPythonOptions): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <PythonInstallSnippet />
            <h3>Configure</h3>
            <PythonSetupSnippet {...props} />
        </>
    )
}
