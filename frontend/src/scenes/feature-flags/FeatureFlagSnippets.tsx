import React from 'react'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

export const UTM_TAGS = '?utm_medium=in-product&utm_campaign=feature-flag'

export function NodeJSSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const isMyFlagEnabledForUser = await client.isFeatureEnabled('${flagKey}', 'user distinct id')

if (isMyFlagEnabledForUser) {
    // Do something differently for this user
}`}
            </CodeSnippet>
        </>
    )
}

export function JSSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // run your activation code here
}`}
            </CodeSnippet>
        </>
    )
}

export function PHPSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.PHP} wrap>
                {`if (PostHog::isFeatureEnabled('${flagKey}', 'some distinct id')) {
    // do something here
}`}
            </CodeSnippet>
        </>
    )
}

export function GolangSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`isFlagEnabledForUser, err := client.IsFeatureEnabled('${flagKey}', 'user distinct id', false)

if (isFlagEnabledForUser) {
  // Do something differently for this user
}`}
            </CodeSnippet>
        </>
    )
}

export function RubySnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`is_my_flag_enabled = posthog.is_feature_enabled('${flagKey}', 'user distinct id')

if is_my_flag_enabled
  # Do something differently for this user
end`}
            </CodeSnippet>
        </>
    )
}

export function PythonSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`if posthog.feature_enabled("${flagKey}", "user_distinct_id"):
    runAwesomeFeature()
`}
            </CodeSnippet>
        </>
    )
}

export function APISnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <>
            <CodeSnippet language={Language.Bash} wrap>
                {`curl ${window.location.origin}/decide/ \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${currentTeam ? currentTeam.api_token : '[project_api_key]'}",
    "distinct_id": "[user distinct id]"
}'
                `}
            </CodeSnippet>
        </>
    )
}
