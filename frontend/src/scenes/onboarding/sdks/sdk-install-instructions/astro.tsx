import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useJsSnippet } from 'lib/components/JSSnippet'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import SetupWizardBanner from './components/SetupWizardBanner'
import { LemonDivider } from '@posthog/lemon-ui'

function CreatePostHogAstroFileSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {`cd ./src/components 
# or 'cd ./src && mkdir components && cd ./components' if your components folder doesn't exist 
touch posthog.astro`}
        </CodeSnippet>
    )
}

function AstroSetupSnippet(): JSX.Element {
    const jsSnippetScriptTag = useJsSnippet()
    return (
        <>
            <CodeSnippet language={Language.JavaScript}>
                {`---

---
${jsSnippetScriptTag}
`}
            </CodeSnippet>
        </>
    )
}

export function SDKInstallAstroInstructions({ hideWizard }: { hideWizard?: boolean }): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)
    const showSetupWizard = !hideWizard && isCloudOrDev
    return (
        <>
            {showSetupWizard && (
                <>
                    <h2>Automated Installation</h2>
                    <SetupWizardBanner integrationName="Astro" />
                    <LemonDivider label="OR" />
                    <h2>Manual Installation</h2>
                </>
            )}
            <h3>Install the PostHog web snippet</h3>
            <p>
                In your <code>src/components</code> folder, create a <code>posthog.astro</code> file:
            </p>
            <CreatePostHogAstroFileSnippet />
            <p>In this file, add your PostHog web snippet:</p>
            <AstroSetupSnippet />
        </>
    )
}
