import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { LemonDivider } from '@posthog/lemon-ui'

function JSEventSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>{`posthog.capture('my event', { property: 'value' })`}</CodeSnippet>
    )
}

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <LemonDivider thick dashed className="my-4" />
            <h4>Send your first event</h4>
            <JSEventSnippet />
        </>
    )
}
