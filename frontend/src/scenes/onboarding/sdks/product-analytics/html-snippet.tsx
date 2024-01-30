import { LemonDivider } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'

function JSEventSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>{`posthog.capture('my event', { property: 'value' })`}</CodeSnippet>
    )
}

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <LemonDivider thick dashed className="my-4" />
            <h4>Optional: Send your first event</h4>
            <p>Our snippet will autocapture events for you, but you can manually capture events, too!</p>
            <JSEventSnippet />
        </>
    )
}
