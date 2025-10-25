import { useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useJsSnippet } from 'lib/components/JSSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import SetupWizardBanner from './components/SetupWizardBanner'

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
    const jsSnippetScriptTag = useJsSnippet(0, undefined, 'is:inline')
    return (
        <>
            <CodeSnippet language={Language.JavaScript}>
                {`---
// src/components/posthog.astro
---
${jsSnippetScriptTag}
`}
            </CodeSnippet>
        </>
    )
}

function CreateLayoutSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {`cd ./src/layouts
# or 'cd ./src && mkdir layouts && cd ./layouts' if your layouts folder doesn't exist 
touch PostHogLayout.astro`}
        </CodeSnippet>
    )
}

function LayoutCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`---
import PostHog from '../components/posthog.astro'
---
<head>
    <PostHog />
</head>`}
        </CodeSnippet>
    )
}

function IndexPageSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`---
import PostHogLayout from '../layouts/PostHogLayout.astro';
---
<PostHogLayout>
  <!-- your existing app components -->
</PostHogLayout>`}
        </CodeSnippet>
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
            <h3>1. Create the PostHog component</h3>
            <p>
                In your <code>src/components</code> folder, create a <code>posthog.astro</code> file:
            </p>
            <CreatePostHogAstroFileSnippet />
            <p>
                In this file, add your PostHog web snippet. Be sure to include the <code>is:inline</code> directive{' '}
                <Link
                    to="https://docs.astro.build/en/guides/client-side-scripts/#opting-out-of-processing"
                    target="_blank"
                >
                    to prevent Astro from processing it
                </Link>
                , or you will get TypeScript and build errors that property 'posthog' does not exist on type 'Window &
                typeof globalThis':
            </p>
            <AstroSetupSnippet />

            <h3>2. Create a layout</h3>
            <p>
                Create a layout where we will use <code>posthog.astro</code>. Create a new file{' '}
                <code>PostHogLayout.astro</code> in your <code>src/layouts</code> folder:
            </p>
            <CreateLayoutSnippet />
            <p>
                Add the following code to <code>PostHogLayout.astro</code>:
            </p>
            <LayoutCodeSnippet />

            <h3>3. Use the layout in your pages</h3>
            <p>
                Finally, update your pages (like <code>index.astro</code>) to wrap your existing app components with the
                new layout:
            </p>
            <IndexPageSnippet />
        </>
    )
}
