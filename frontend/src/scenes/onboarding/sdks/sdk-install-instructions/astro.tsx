import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useJsSnippet } from 'lib/components/JSSnippet'

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

export function SDKInstallAstroInstructions(): JSX.Element {
    return (
        <>
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
