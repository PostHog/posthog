import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function VerifySourceMaps(): JSX.Element {
    return (
        <>
            <h3>Verify source map injection</h3>
            <p>
                Before proceeding, confirm that source maps are being properly injected. You can verify the injection is
                successful by checking your source map files for <code>//# chunkId=</code> comments.
            </p>
            <p>
                Make sure to serve these injected files in production. PostHog will check for the{' '}
                <code>//# chunkId</code> comments to display the correct stack traces.
            </p>
            <CodeSnippet language={Language.JavaScript}>//# chunkId=0197e6db-9a73-7b91-9e80-4e1b7158db5c</CodeSnippet>

            <h3>Verify source map upload</h3>
            <p>After exiting this modal, you will see source maps status updates.</p>
        </>
    )
}
