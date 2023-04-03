import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function NodeJSPayloadSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const matchedFlagPayload = await client.getFeatureFlagPayload('${flagKey}', 'user distinct id')`}
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

export function PythonPayloadSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`posthog.get_feature_flag_payload(${flagKey}, "user_distinct_id")`}
            </CodeSnippet>
        </>
    )
}

export function RubyPayloadSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`posthog.get_feature_flag_payload(${flagKey}, "user_distinct_id")`}
            </CodeSnippet>
        </>
    )
}
