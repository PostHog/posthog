import { LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import SetupWizardBanner from './components/SetupWizardBanner'
import { JSInstallSnippet } from './js-web'
import { SDK_DEFAULTS_DATE } from './constants'

function ReactEnvVarsSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Bash}>
            {[`VITE_PUBLIC_POSTHOG_KEY=${currentTeam?.api_token}`, `VITE_PUBLIC_POSTHOG_HOST=${apiHostOrigin()}`].join(
                '\n'
            )}
        </CodeSnippet>
    )
}

function ReactSetupSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { PostHogProvider } from 'posthog-js/react'

const options = {
  api_host: import.meta.env.VITE_PUBLIC_POSTHOG_HOST,
  defaults: '${SDK_DEFAULTS_DATE}',
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <PostHogProvider apiKey={import.meta.env.VITE_PUBLIC_POSTHOG_KEY} options={options}>
      <App />
    </PostHogProvider>
  </StrictMode>,
);`}
        </CodeSnippet>
    )
}

export function SDKInstallReactInstructions({ hideWizard }: { hideWizard?: boolean }): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)
    const showSetupWizard = useFeatureFlag('AI_SETUP_WIZARD') && !hideWizard && isCloudOrDev
    return (
        <>
            {showSetupWizard && (
                <>
                    <h2>Automated Installation</h2>
                    <SetupWizardBanner integrationName="React" />
                    <LemonDivider label="OR" />
                    <h2>Manual Installation</h2>
                </>
            )}
            <h3>Install the package</h3>
            <JSInstallSnippet />
            <h3>Add environment variables</h3>
            <ReactEnvVarsSnippet />
            <h3>Initialize</h3>
            <p>
                Integrate PostHog at the root of your app (such as <code>main.tsx</code> if you're using Vite).
            </p>
            <ReactSetupSnippet />
        </>
    )
}
