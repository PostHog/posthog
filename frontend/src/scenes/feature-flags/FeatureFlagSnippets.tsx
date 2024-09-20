import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { GroupType } from '~/types'

export const UTM_TAGS = '?utm_medium=in-product&utm_campaign=feature-flag'

export interface FeatureFlagSnippet {
    flagKey: string
    multivariant?: boolean
    groupType?: GroupType
    localEvaluation?: boolean
    payload?: boolean
    samplePropertyName?: string
    instantlyAvailableProperties?: boolean
}

const LOCAL_EVAL_REMINDER = `Remember to set a personal API key in the SDK to enable local evaluation.
`

export function NodeJSSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    payload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'await client.'
    const flagFunction = payload ? 'getFeatureFlagPayload' : multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const propertyName = samplePropertyName || 'is_authorized'

    const localEvalAddition = localEvaluation
        ? groupType
            ? `
        // add group properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        groupProperties: { ${groupType.group_type}: {'${propertyName}': 'value', 'name': 'xyz'}}`
            : `
        // add person properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        personProperties: {'${propertyName}': 'value'}`
        : ''

    const flagSnippet = groupType
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',${
        payload
            ? `
    undefined,`
            : ''
    }
    {
        groups: { '${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>' },${localEvalAddition}
    }
)`
        : localEvalAddition
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',${
        payload
            ? `
    undefined,`
            : ''
    }
    {${localEvalAddition}
    }
)`
        : `${clientSuffix}${flagFunction}('${flagKey}', 'user distinct id')`

    const variableName = payload ? 'matchedFlagPayload' : multivariant ? 'enabledVariant' : 'isMyFlagEnabledForUser'

    const conditional = multivariant ? `${variableName} === 'example-variant'` : `${variableName}`

    const followUpCode = payload
        ? ''
        : `

if (${conditional}) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`

    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`${
                    localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''
                }const ${variableName} = ${flagSnippet}${followUpCode}`}
            </CodeSnippet>
        </>
    )
}

export function PHPSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'PostHog::'

    const flagFunction = multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const propertyName = samplePropertyName || 'is_authorized'

    const localEvalAddition = localEvaluation
        ? groupType
            ? `
    // empty person properties
    [],
    // add group properties used in the flag to ensure the flag
    // is evaluated locally, vs. going to our servers
    [${groupType.group_type} =>  ['${propertyName}' => 'value', 'name' => 'xyz']]`
            : `
    // add person properties used in the flag to ensure the flag
    // is evaluated locally, vs. going to our servers
    ['${propertyName}' => 'value']`
        : ''

    const flagSnippet = groupType
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',
    // group types
    ['${groupType.group_type}' => '<${groupType.name_singular || 'group'} ID>'],${localEvalAddition}
)`
        : localEvalAddition
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',${localEvalAddition}
)`
        : `${clientSuffix}${flagFunction}('${flagKey}', 'user distinct id')`
    const variableName = multivariant ? '$enabledVariant' : '$isMyFlagEnabledForUser'

    const conditional = multivariant ? `${variableName} === 'example-variant'` : `${variableName}`

    return (
        <>
            <CodeSnippet language={Language.PHP} wrap>
                {`${localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''}${variableName} = ${flagSnippet}

if (${conditional}) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`}
            </CodeSnippet>
        </>
    )
}

export function GolangSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'client.'

    const flagFunction = multivariant ? 'GetFeatureFlag' : 'IsFeatureEnabled'

    const propertyName = samplePropertyName || 'is_authorized'

    const localEvalAddition = localEvaluation
        ? groupType
            ? `
        // add group properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        groupProperties: map[string]Properties{"${groupType.group_type}": posthog.NewProperties().Set("${propertyName}", "value").Set("name", "xyz")}`
            : `
        // add person properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        PersonProperties: posthog.NewProperties().Set("${propertyName}", "value")`
        : ''

    const flagSnippet = groupType
        ? `${clientSuffix}${flagFunction}(
    FeatureFlagPayload{
        Key:        "${flagKey}",
        DistinctId: "distinct-id",
        Groups:     Groups{'${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>'},${localEvalAddition}
    }
)`
        : `${clientSuffix}${flagFunction}(
    FeatureFlagPayload{
        Key:        '${flagKey}',
        DistinctId: "distinct-id",${localEvalAddition}
    })`
    const variableName = multivariant ? 'enabledVariant, err' : 'isMyFlagEnabledForUser, err'

    const conditional = multivariant ? `enabledVariant == 'example-variant'` : `isMyFlagEnabledForUser`

    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`${localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''}${variableName} := ${flagSnippet}

if ${conditional} {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`}
            </CodeSnippet>
        </>
    )
}

export function RubySnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    payload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'posthog.'
    const flagFunction = payload ? 'get_feature_flag_payload' : multivariant ? 'get_feature_flag' : 'is_feature_enabled'

    const propertyName = samplePropertyName || 'is_authorized'

    const localEvalAddition = localEvaluation
        ? groupType
            ? `
    # add group properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    group_properties: { ${groupType.group_type}: {'${propertyName}': 'value', 'name': 'xyz'}}`
            : `
    # add person properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    person_properties: {'${propertyName}': 'value'}`
        : ''

    const flagSnippet = groupType
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',
    groups: { '${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>' },${localEvalAddition}
)`
        : localEvalAddition
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',${localEvalAddition}
)`
        : `${clientSuffix}${flagFunction}('${flagKey}', 'user distinct id')`
    const variableName = payload ? 'matched_flag_payload' : multivariant ? 'enabled_variant' : 'is_my_flag_enabled'

    const conditional = multivariant ? `${variableName} == 'example-variant'` : `${variableName}`

    const followUpCode = payload
        ? ''
        : `

if ${conditional}
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
end`

    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`${localEvaluation ? '# ' + LOCAL_EVAL_REMINDER : ''}${variableName} = ${flagSnippet}${followUpCode}`}
            </CodeSnippet>
        </>
    )
}

export function PythonSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    payload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'posthog.'
    const flagFunction = payload ? 'get_feature_flag_payload' : multivariant ? 'get_feature_flag' : 'feature_enabled'

    const propertyName = samplePropertyName || 'is_authorized'

    const localEvalAddition = localEvaluation
        ? groupType
            ? `
    # add group properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    group_properties={ ${groupType.group_type}: {'${propertyName}': 'value', 'name': 'xyz'}}`
            : `
    # add person properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    person_properties={'${propertyName}': 'value'}`
        : ''

    const flagSnippet = groupType
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',
    groups={ '${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>' },${localEvalAddition}
)`
        : localEvalAddition
        ? `${clientSuffix}${flagFunction}(
    '${flagKey}',
    'user distinct id',${localEvalAddition}
)`
        : `${clientSuffix}${flagFunction}('${flagKey}', 'user distinct id')`
    const variableName = payload ? 'matched_flag_payload' : multivariant ? 'enabled_variant' : 'is_my_flag_enabled'

    const conditional = multivariant ? `${variableName} == 'example-variant'` : `${variableName}`

    const followUpCode = payload
        ? ''
        : `

if ${conditional}:
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
`

    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`${localEvaluation ? '# ' + LOCAL_EVAL_REMINDER : ''}${variableName} = ${flagSnippet}${followUpCode}`}
            </CodeSnippet>
        </>
    )
}

export function AndroidSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'PostHog.'

    if (payload) {
        return (
            <CodeSnippet language={Language.Kotlin} wrap>
                {`${clientSuffix}getFeatureFlagPayload("${flagKey}")`}
            </CodeSnippet>
        )
    }

    const flagFunction = multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const variantSuffix = multivariant ? ` == "example-variant"` : ''
    return (
        <CodeSnippet language={Language.Kotlin} wrap>
            {`if (${clientSuffix}${flagFunction}("${flagKey}")${variantSuffix}) {
    // do something
}
            `}
        </CodeSnippet>
    )
}

export function FlutterSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'await Posthog().'

    if (payload) {
        return (
            <CodeSnippet language={Language.Dart} wrap>
                {`${clientSuffix}getFeatureFlagPayload('${flagKey}');`}
            </CodeSnippet>
        )
    }

    const flagFunction = multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const variantSuffix = multivariant ? ` == 'example-variant'` : ''

    return (
        <CodeSnippet language={Language.Dart} wrap>
            {`if (${clientSuffix}${flagFunction}('${flagKey}')${variantSuffix}) {
    // do something
}
            `}
        </CodeSnippet>
    )
}

export function iOSSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'PostHogSDK.shared.'

    if (payload) {
        return (
            <CodeSnippet language={Language.Swift} wrap>
                {`${clientSuffix}getFeatureFlagPayload("${flagKey}")`}
            </CodeSnippet>
        )
    }

    const flagFunction = multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const variantSuffix = multivariant ? `as? String == "example-variant"` : ''
    return (
        <CodeSnippet language={Language.Swift} wrap>
            {`if ${clientSuffix}${flagFunction}("${flagKey}")${variantSuffix} {
    // do something
}`}
        </CodeSnippet>
    )
}

export function ReactNativeSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const clientSuffix = 'posthog.'

    if (payload) {
        return (
            <CodeSnippet language={Language.JSX} wrap>
                {`${clientSuffix}getFeatureFlagPayload('${flagKey}')`}
            </CodeSnippet>
        )
    }

    const flagFunction = multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const variantSuffix = multivariant ? ` == 'example-variant'` : ''
    return (
        <CodeSnippet language={Language.JSX} wrap>
            {`// With a hook
import { useFeatureFlag } from 'posthog-react-native'

const MyComponent = () => {
    const showFlaggedFeature = useFeatureFlag('${flagKey}')

    if (showFlaggedFeature === undefined) {
        // the response is undefined if the flags are being loaded
        return null
    }

    return showFlaggedFeature ${variantSuffix} ? <Text>Testing feature 😄</Text> : <Text>Not Testing feature 😢</Text>
}

// Or calling on the method directly
${clientSuffix}${flagFunction}('${flagKey}')
            `}
        </CodeSnippet>
    )
}

export function ReactSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const flagFunction = payload
        ? 'useFeatureFlagPayload'
        : multivariant
        ? 'useFeatureFlagVariantKey'
        : 'useFeatureFlagEnabled'

    const variable = payload ? 'payload' : multivariant ? 'variant' : 'flagEnabled'
    const variantSuffix = multivariant ? ` == 'example-variant'` : ''

    return (
        <CodeSnippet language={Language.JSX} wrap>
            {`
import { ${flagFunction} } from 'posthog-js/react'

function App() {
    const ${variable} = ${flagFunction}('${flagKey}')

    if (${variable}${variantSuffix}) {
        // do something
    }
}`}
        </CodeSnippet>
    )
}

export function APISnippet({ groupType }: FeatureFlagSnippet): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const groupAddition = groupType
        ? `
    "groups": { "${groupType.group_type}": "<${groupType.name_singular || 'group'} ID>" },`
        : ''

    return (
        <>
            <CodeSnippet language={Language.Bash} wrap>
                {`curl ${apiHostOrigin()}/decide?v=3/ \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${currentTeam ? currentTeam.api_token : '[project_api_key]'}",
    "distinct_id": "[user distinct id]",${groupAddition}
}'
                `}
            </CodeSnippet>
        </>
    )
}

export function JSSnippet({
    flagKey,
    multivariant,
    payload,
    groupType,
    instantlyAvailableProperties,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    if (payload) {
        return (
            <>
                <CodeSnippet language={Language.JavaScript} wrap>
                    {`posthog.getFeatureFlagPayload('${flagKey ?? ''}')`}
                </CodeSnippet>
            </>
        )
    }

    const propertyName = samplePropertyName || 'is_authorized'

    const propertyOverrideSnippet = `// Your flag depends on properties that are not instantly available. If you want
// to make them available without waiting for server delays, send these properties for flag evaluation, like so:
// Make sure to call this before evaluating flags. More info: https://posthog.com/docs/libraries/js#overriding-server-properties 
posthog.${
        groupType
            ? `setGroupPropertiesForFlags({ '${groupType.group_type}': {'${propertyName}': 'value'}})`
            : `setPersonPropertiesForFlags({'${propertyName}': 'value'})`
    }

`

    const clientSuffix = 'posthog.'
    const flagFunction = multivariant ? 'getFeatureFlag' : 'isFeatureEnabled'

    const variantSuffix = multivariant ? ` == 'example-variant'` : ''
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`${instantlyAvailableProperties ? '' : propertyOverrideSnippet}// Ensure flags are loaded before usage.
// You'll only need to call this on the code for when the first time a user visits.
${clientSuffix}onFeatureFlags(function() {
    // feature flags should be available at this point
    if (${clientSuffix}${flagFunction}('${flagKey ?? ''}') ${variantSuffix}) {
        // do something
    }
})

// Otherwise, you can just do:
if (${clientSuffix}${flagFunction}('${flagKey ?? ''}') ${variantSuffix}) {
    // do something
}`}
            </CodeSnippet>
        </>
    )
}

export function JSBootstrappingSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`// Initialise the posthog library with a distinct ID and feature flags for immediate loading
// This avoids the delay between the library loading and feature flags becoming available to use.

posthog.init('{project_api_key}', {
    api_host: '${apiHostOrigin()}'
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
