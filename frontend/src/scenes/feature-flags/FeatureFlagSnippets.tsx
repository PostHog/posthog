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

export function JSMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`// Ensure flags are loaded before usage.
// You'll only need to call this on the code for when the first time a user visits.

posthog.onFeatureFlags(function() {
// feature flags should be available at this point
if (posthog.getFeatureFlag('${flagKey ?? ''}') === 'example-variant') {
// do something
}
})

// Otherwise, you can just do

if (posthog.getFeatureFlag('${flagKey ?? ''}') === 'example-variant') {
// do something
}`}
        </CodeSnippet>
    )
}

export function iOSMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.Swift} wrap>
            {`// In Swift

if (posthog.getFeatureFlag('${flagKey}') == 'example-variant') {
    // do something
}
            `}
        </CodeSnippet>
    )
}

export function AndroidMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.Java} wrap>
            {`if (PostHog.with(this).getFeatureFlag('${flagKey}') == 'example-variant') {
    // do something
}
            `}
        </CodeSnippet>
    )
}

export function ReactNativeMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
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

    return showFlaggedFeature === 'example-variant' ? <Text>Testing feature 😄</Text> : <Text>Not Testing feature 😢</Text>
}

// Or calling on the method directly
posthog.getFeatureFlag('${flagKey ?? ''}') === 'example-variant'
            `}
        </CodeSnippet>
    )
}

export function NodeJSMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const enabledVariant = await client.getFeatureFlag('${flagKey}', 'user distinct id')

if (enabledVariant === 'example-variant') {
    // Do something differently for this user
}`}
            </CodeSnippet>
        </>
    )
}

export function PythonMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`if posthog.get_feature_flag("${flagKey}", "user_distinct_id") == 'example-variant':
    runAwesomeFeature()
`}
            </CodeSnippet>
        </>
    )
}

export function RubyMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`if posthog.get_feature_flag('${flagKey}', 'user distinct id') == 'example-variant'
  # Do something
end`}
            </CodeSnippet>
        </>
    )
}

export function GolangMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`enabledVariant, err := client.GetFeatureFlag(
                    FeatureFlagPayload{
                        Key:        '${flagKey}',
                        DistinctId: "distinct-id",
                    })

if (enabledVariant == 'example-variant') {
  // Do something differently for this user
}`}
            </CodeSnippet>
        </>
    )
}

export function PHPMultivariateSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.PHP} wrap>
                {`if (PostHog::getFeatureFlag('${flagKey}', 'some distinct id') === 'example-variant') {
    // do something here
}`}
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
// add person or group properties used in the flag to ensure the flag is evaluated locally, vs. going to our servers
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
// add person or group properties used in the flag to ensure the flag is evaluated locally, vs. going to our servers
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
// add person or group properties used in the flag to ensure the flag is evaluated locally
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
// add person or group properties used in the flag to ensure the flag is evaluated locally, vs. going to our servers
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
// add person or group properties used in the flag to ensure the flag is evaluated locally, vs. going to our servers
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
            {`// Initialise the posthog library with a distinct ID and feature flags for immediate loading

posthog.init('{project_api_key}', {
    api_host: 'https://app.posthog.com',
    bootstrap:
    {
        distinctID: 'your-anonymous-id',
        featureFlags: {
    // input the flag values here from 'posthog.getAllFlags(distinct_id)' which you can find in the server-side libraries.
        // example:
            // 'flag-1': true,
            // 'variant-flag': 'control',
            // 'other-flag': false
        },
    }
})
            `}
        </CodeSnippet>
    )
}
