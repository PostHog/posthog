import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
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
                {`// Ensure flags are loaded before usage.
// You'll only need to call this on the code for when the first time a user visits.

posthog.onFeatureFlags(function() {
    // feature flags should be available at this point
    if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
        // do something
    }
})

// Otherwise, you can just do

if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // do something
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
                {`isFlagEnabledForUser, err := client.IsFeatureEnabled(
                    FeatureFlagPayload{
                        Key:        '${flagKey}',
                        DistinctId: "distinct-id",
                    })

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
                {`if posthog.feature_enabled("${flagKey}", "user_distinct_id"):
    runAwesomeFeature()
`}
            </CodeSnippet>
        </>
    )
}

export function AndroidSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.Java} wrap>
            {`if (PostHog.with(this).isFeatureEnabled('${flagKey}')) {
    // do something
}
            `}
        </CodeSnippet>
    )
}

export function iOSSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.Swift} wrap>
            {`// In Swift

if (posthog.isFeatureEnabled('${flagKey}')) {
    // do something
}
            `}
        </CodeSnippet>
    )
}

export function ReactNativeSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.Java} wrap>
            {`// With a hook
import { useFeatureFlag } from 'posthog-react-native'

const MyComponent = () => {
    const showFlaggedFeature = useFeatureFlag('${flagKey}')

    if (showFlaggedFeature === undefined) {
        // the response is undefined if the flags are being loaded
        return null
    }

    return showFlaggedFeature ? <Text>Testing feature 😄</Text> : <Text>Not Testing feature 😢</Text>
}

// Or calling on the method directly
posthog.getFeatureFlag('my-flag')
            `}
        </CodeSnippet>
    )
}

export function APISnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <>
            <CodeSnippet language={Language.Bash} wrap>
                {`curl ${window.location.origin}/decide?v=2/ \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${currentTeam ? currentTeam.api_token : '[project_api_key]'}",
    "distinct_id": "[user distinct id]",
}'
                `}
            </CodeSnippet>
        </>
    )
}

export function PythonLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`posthog.get_feature_flag(
    ${flagKey},
    'distinct id',
    person_properties={'is_authorized': True}
)

`}
            </CodeSnippet>
        </>
    )
}

export function RubyLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`posthog.get_feature_flag(
    ${flagKey},
    'distinct id',
    person_properties: {'is_authorized': true}
)

`}
            </CodeSnippet>
        </>
    )
}

export function NodeLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`await client.getFeatureFlag(
    ${flagKey},
    'distinct id',
    {
        personProperties: {'is_authorized': true}
    }
)`}
        </CodeSnippet>
    )
}

export function PHPLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.PHP} wrap>
            {`PostHog::getFeatureFlag(
    ${flagKey},
    'distinct id',
    [], // group properties
    ["is_authorized" => true] // person properties
)
            `}
        </CodeSnippet>
    )
}

export function GolangLocalEvaluationSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`enabledVariant, err := client.GetFeatureFlag(
        FeatureFlagPayload{
            Key:        ${flagKey},
            DistinctId: "distinct-id",
      PersonProperties: posthog.NewProperties().
        Set("is_authorized", true),
        },
)`}
            </CodeSnippet>
        </>
    )
}

export function JSBootstrappingSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.init('{project_api_key}', {
    api_host: 'https://app.posthog.com',
    bootstrap: {
        distinctID: 'your-anonymous-id',
        featureFlags: {
            'flag-1': true,
            'variant-flag': 'control',
            'other-flag': false
        }
    }
})
            `}
        </CodeSnippet>
    )
}
