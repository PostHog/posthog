import { LemonDivider } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'

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
            <h4>Optional: Send a manual event</h4>
            <p>Our package will autocapture events for you, but you can manually define events, too!</p>
            <JSEventSnippet />
        </>
    )
}
