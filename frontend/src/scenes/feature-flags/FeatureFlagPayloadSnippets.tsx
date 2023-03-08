import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function NodeJSPayloadSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const matchedFlayPayload = await client.getFeatureFlagPayload('${flagKey}', 'user distinct id')`}
            </CodeSnippet>
        </>
    )
}

export function JSPayloadSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`posthog.getFeatureFlagPayload('${flagKey ?? ''}')`}
            </CodeSnippet>
        </>
    )
}
