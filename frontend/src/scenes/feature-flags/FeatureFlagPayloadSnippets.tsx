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
                {`posthog.get_feature_flag_payload("${flagKey}", "user_distinct_id")`}
            </CodeSnippet>
        </>
    )
}

export function RubyPayloadSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`posthog.get_feature_flag_payload("${flagKey}", "user_distinct_id")`}
            </CodeSnippet>
        </>
    )
}

export function NodeJSPayloadLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const matchedFlagPayload = await client.getFeatureFlagPayload(
                    '${flagKey}',
                    'user distinct id'
                    // add person or group properties used in the flag to ensure the flag is evaluated locally
                    {
                        personProperties: {'email': 'a@b.com'},
                    }
                )`}
            </CodeSnippet>
        </>
    )
}

export function PythonPayloadLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`posthog.get_feature_flag_payload(
                    "${flagKey}",
                    "user_distinct_id",
                    // add person or group properties used in the flag to ensure the flag is evaluated locally, vs. going to our servers
                    person_properties={'email': 'a@b.com'}
                )`}
            </CodeSnippet>
        </>
    )
}

export function RubyPayloadLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`posthog.get_feature_flag_payload(
                    "${flagKey}",
                    "user_distinct_id",
                    // add person or group properties used in the flag to ensure the flag is evaluated locally, vs. going to our servers
                    person_properties: {'email': 'a@b.com'}
                )`}
            </CodeSnippet>
        </>
    )
}
