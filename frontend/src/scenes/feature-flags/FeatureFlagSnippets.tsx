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
    remoteConfiguration?: boolean
    encryptedPayload?: boolean
    samplePropertyName?: string
    instantlyAvailableProperties?: boolean
}

const LOCAL_EVAL_REMINDER = `Remember to set a feature flags secure API key in the SDK to enable local evaluation.
`

const REMOTE_CONFIG_REMINDER = `Must initialize SDK with a feature flags secure API key to enable remote configuration.`
const ENCRYPTED_PAYLOAD_REMINDER = `Encrypted payloads are automatically decrypted on the server before being sent to the client.`

export function NodeJSSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    payload,
    remoteConfiguration,
    encryptedPayload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const propertyName = samplePropertyName || 'is_authorized'

    if (remoteConfiguration) {
        const reminder = REMOTE_CONFIG_REMINDER + (encryptedPayload ? `\n// ${ENCRYPTED_PAYLOAD_REMINDER}` : '')

        return (
            <>
                <CodeSnippet language={Language.JavaScript} wrap>
                    {`// ${reminder}
const remoteConfigPayload = await client.getRemoteConfigPayload('${flagKey}')`}
                </CodeSnippet>
            </>
        )
    }

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
        ? `await client.getFeatureFlagResult(
    '${flagKey}',
    'user distinct id',
    {
        groups: { '${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>' },${localEvalAddition}
    }
)`
        : localEvalAddition
          ? `await client.getFeatureFlagResult(
    '${flagKey}',
    'user distinct id',
    {${localEvalAddition}
    }
)`
          : `await client.getFeatureFlagResult('${flagKey}', 'user distinct id')`

    const flagCheck = multivariant
        ? `

if (result?.variant === 'example-variant') {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`
        : payload
          ? `

if (result?.enabled) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
    if (result?.payload) {
        // result.payload contains a JSON value (string, number, boolean, object, or array)
        // Do something with the payload
    }
}`
          : `

if (result?.enabled) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`

    const payloadCode =
        payload && multivariant
            ? `

if (result?.payload) {
    // result.payload contains a JSON value (string, number, boolean, object, or array)
    // Do something with the payload
}`
            : ''

    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`${
                    localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''
                }const result = ${flagSnippet}${flagCheck}${payloadCode}`}
            </CodeSnippet>
        </>
    )
}

export function PHPSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    payload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
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
        ? `PostHog::getFeatureFlagResult(
    '${flagKey}',
    'user distinct id',
    // group types
    ['${groupType.group_type}' => '<${groupType.name_singular || 'group'} ID>'],${localEvalAddition}
)`
        : localEvalAddition
          ? `PostHog::getFeatureFlagResult(
    '${flagKey}',
    'user distinct id',${localEvalAddition}
)`
          : `PostHog::getFeatureFlagResult('${flagKey}', 'user distinct id')`

    const flagCheck = multivariant
        ? `

if ($result?->getVariant() === 'example-variant') {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`
        : payload
          ? `

if ($result?->isEnabled()) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
    if ($result?->getPayload()) {
        // getPayload() returns a JSON value (string, number, boolean, array, or object)
    }
}`
          : `

if ($result?->isEnabled()) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`

    const payloadCode =
        payload && multivariant
            ? `

// getPayload() returns a JSON value (string, number, boolean, array, or object)
if ($result?->getPayload()) {
    // Do something with the payload
}`
            : ''

    return (
        <>
            <CodeSnippet language={Language.PHP} wrap>
                {`${localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''}$result = ${flagSnippet};${flagCheck}${payloadCode}`}
            </CodeSnippet>
        </>
    )
}

export function GolangSnippet({
    flagKey,
    groupType,
    payload,
    remoteConfiguration,
    encryptedPayload,
    multivariant,
    localEvaluation,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const propertyName = samplePropertyName || 'is_authorized'

    if (remoteConfiguration) {
        const reminder = REMOTE_CONFIG_REMINDER + (encryptedPayload ? `\n// ${ENCRYPTED_PAYLOAD_REMINDER}` : '')

        return (
            <>
                <CodeSnippet language={Language.Go} wrap>
                    {`// ${reminder}
remoteConfigPayload, err := client.GetRemoteConfigPayload("${flagKey}")`}
                </CodeSnippet>
            </>
        )
    }

    const localEvalAddition = localEvaluation
        ? groupType
            ? `
    // add group properties used in the flag to ensure the flag
    // is evaluated locally, vs. going to our servers
    GroupProperties: map[string]Properties{"${groupType.group_type}": posthog.NewProperties().Set("${propertyName}", "value").Set("name", "xyz")}`
            : `
    // add person properties used in the flag to ensure the flag
    // is evaluated locally, vs. going to our servers
    PersonProperties: posthog.NewProperties().Set("${propertyName}", "value")`
        : ''

    const flagSnippet = groupType
        ? `client.GetFeatureFlagResult(posthog.FeatureFlagPayload{
        Key:        "${flagKey}",
        DistinctId: "distinct-id",
        Groups:     Groups{"${groupType.group_type}": "<${groupType.name_singular || 'group'} ID>"},${localEvalAddition}
    }
)`
        : `client.GetFeatureFlagResult(posthog.FeatureFlagPayload{
    Key:        "${flagKey}",
    DistinctId: "distinct-id",${localEvalAddition}
})`

    const flagCheck = multivariant
        ? `
if result.Variant != nil && *result.Variant == "example-variant" {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`
        : payload
          ? `
if result.Enabled {
    // Unmarshal the payload into a typed struct
    var config MyConfig
    if err := result.GetPayloadAs(&config); err == nil {
        fmt.Println(config)
    }

    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`
          : `
if result.Enabled {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`

    const payloadCode =
        payload && multivariant
            ? `

// Unmarshal the payload into a typed struct
var config MyConfig
if err := result.GetPayloadAs(&config); err == nil {
    fmt.Println(config)
}`
            : ''

    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`${localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''}result, err := ${flagSnippet}
if err != nil {
    // Handle error
    // e.g. posthog.ErrFlagNotFound if flag doesn't exist
    return
}
${flagCheck}${payloadCode}`}
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
    remoteConfiguration,
    encryptedPayload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const propertyName = samplePropertyName || 'is_authorized'

    if (remoteConfiguration) {
        const reminder = `# ` + REMOTE_CONFIG_REMINDER + (encryptedPayload ? `\n# ${ENCRYPTED_PAYLOAD_REMINDER}` : '')

        return (
            <>
                <CodeSnippet language={Language.Ruby} wrap>
                    {`${reminder}
remote_config_payload = posthog.get_remote_config_payload('${flagKey}')`}
                </CodeSnippet>
            </>
        )
    }

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
        ? `posthog.get_feature_flag_result(
    '${flagKey}',
    'user distinct id',
    groups: { '${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>' },${localEvalAddition}
)`
        : localEvalAddition
          ? `posthog.get_feature_flag_result(
    '${flagKey}',
    'user distinct id',${localEvalAddition}
)`
          : `posthog.get_feature_flag_result('${flagKey}', 'user distinct id')`

    const flagCheck = multivariant
        ? `

if result&.variant == 'example-variant'
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
end`
        : payload
          ? `

if result&.enabled?
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
    if result.payload
        # result.payload contains a JSON value (String, Numeric, Boolean, Hash, or Array)
    end
end`
          : `

if result&.enabled?
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
end`

    const payloadCode =
        payload && multivariant
            ? `

if result&.payload
    # result.payload contains a JSON value (String, Numeric, Boolean, Hash, or Array)
    # Do something with the payload
end`
            : ''

    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`${localEvaluation ? '# ' + LOCAL_EVAL_REMINDER : ''}result = ${flagSnippet}${flagCheck}${payloadCode}`}
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
    remoteConfiguration,
    encryptedPayload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const propertyName = samplePropertyName || 'is_authorized'

    if (remoteConfiguration) {
        const reminder = `# ` + REMOTE_CONFIG_REMINDER + (encryptedPayload ? `\n# ${ENCRYPTED_PAYLOAD_REMINDER}` : '')

        return (
            <>
                <CodeSnippet language={Language.Python} wrap>
                    {`${reminder}
remote_config_payload = posthog.get_remote_config_payload('${flagKey}')`}
                </CodeSnippet>
            </>
        )
    }

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
        ? `posthog.get_feature_flag_result(
    '${flagKey}',
    'user distinct id',
    groups={ '${groupType.group_type}': '<${groupType.name_singular || 'group'} ID>' },${localEvalAddition}
)`
        : localEvalAddition
          ? `posthog.get_feature_flag_result(
    '${flagKey}',
    'user distinct id',${localEvalAddition}
)`
          : `posthog.get_feature_flag_result('${flagKey}', 'user distinct id')`

    const flagCheck = multivariant
        ? `

if result and result.variant == 'example-variant':
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
`
        : payload
          ? `

if result and result.enabled:
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
    if result.payload:
        # result.payload contains a JSON value (str, int, float, bool, dict, or list)
`
          : `

if result and result.enabled:
    # Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
`

    const payloadCode =
        payload && multivariant
            ? `
if result and result.payload:
    # result.payload contains a JSON value (str, int, float, bool, dict, or list)
`
            : ''

    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`${localEvaluation ? '# ' + LOCAL_EVAL_REMINDER : ''}result = ${flagSnippet}${flagCheck}${payloadCode}`}
            </CodeSnippet>
        </>
    )
}

export function CSharpSnippet({
    flagKey,
    groupType,
    multivariant,
    localEvaluation,
    payload,
    remoteConfiguration,
    encryptedPayload,
    samplePropertyName,
}: FeatureFlagSnippet): JSX.Element {
    const propertyName = samplePropertyName || 'isAuthorized'

    if (remoteConfiguration) {
        const reminder = `// ` + REMOTE_CONFIG_REMINDER + (encryptedPayload ? `\n// ${ENCRYPTED_PAYLOAD_REMINDER}` : '')

        return (
            <>
                <CodeSnippet language={Language.CSharp} wrap>
                    {`${reminder}
var remoteConfigPayload = await posthog.GetRemoteConfigPayloadAsync("${flagKey}");`}
                </CodeSnippet>
            </>
        )
    }

    const localEvalCommentAddition = localEvaluation
        ? groupType
            ? `// add group properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        `
            : `// add person properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        `
        : ''

    const localEvalCodeAddition = localEvaluation
        ? groupType
            ? `{ ["${propertyName}"] = "value", ["name"] = "xyz" }`
            : `
    personProperties: new() { ["${propertyName}"] = "value" }`
        : ''

    const flagSnippet = groupType
        ? `await posthog.GetFeatureFlagAsync(
    "${flagKey}",
    "user distinct id",
    new FeatureFlagOptions
    {
        ${localEvalCommentAddition}Groups = [new Group("${groupType.group_type}", "<${
            groupType.name_singular || 'group'
        } ID>")${localEvalCodeAddition}]
    }
);`
        : localEvalCodeAddition
          ? `await posthog.GetFeatureFlagAsync(
    "${flagKey}",
    "user distinct id",${localEvalCodeAddition}
);`
          : `await posthog.GetFeatureFlagAsync("${flagKey}", "user distinct id");`

    const flagCheck = multivariant
        ? `

if (flag?.VariantKey == "example-variant") {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`
        : payload
          ? `
if (flag?.IsEnabled == true) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
    if (flag?.Payload is { } payload) {
        try {
            // payload is a JsonDocument — deserialize into a typed object
            var config = payload.RootElement.Deserialize<MyConfig>();
        } catch (JsonException) { }
    }
}`
          : `
if (flag?.IsEnabled == true) {
    // Do something differently for this ${groupType ? groupType.name_singular || 'group' : 'user'}
}`

    const payloadCode =
        payload && multivariant
            ? `

if (flag?.Payload is { } payload)
{
    try {
        // flag.Payload is a JsonDocument — deserialize into a typed object
        var config = payload.RootElement.Deserialize<MyConfig>();
    } catch (JsonException) { }
}`
            : ''

    return (
        <>
            <CodeSnippet language={Language.CSharp} wrap>
                {`${
                    localEvaluation ? '// ' + LOCAL_EVAL_REMINDER : ''
                }var flag = ${flagSnippet}${flagCheck}${payloadCode}`}
            </CodeSnippet>
        </>
    )
}

export function JavaSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const distinctId = 'user distinct id'

    const flagCheck = multivariant
        ? `
if (result != null && "example-variant".equals(result.getVariant())) {
    // Do something differently for this user
}`
        : payload
          ? `
if (result != null && result.getEnabled()) {
    // Do something differently for this user
    if (result.getPayload() != null) {
        // result.getPayload() contains the deserialized JSON value (Map, List, String, etc.)
        // Optionally deserialize the payload into a typed object
        MyConfig config = result.getPayloadAs(MyConfig.class);
    }
}`
          : `
if (result != null && result.getEnabled()) {
    // Do something differently for this user
}`

    const payloadCode =
        payload && multivariant
            ? `

if (result != null && result.getPayload() != null) {
    // result.getPayload() contains the deserialized JSON value (Map, List, String, etc.)
    // Optionally deserialize the payload into a typed object
    MyConfig config = result.getPayloadAs(MyConfig.class);
}`
            : ''

    return (
        <>
            <CodeSnippet language={Language.Java} wrap>
                {`FeatureFlagResult result = postHog.getFeatureFlagResult("${distinctId}", "${flagKey}");${flagCheck}${payloadCode}`}
            </CodeSnippet>
        </>
    )
}

export function AndroidSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const flagCheck = multivariant
        ? `
if (result?.variant == "example-variant") {
    // Do something differently for this user
}`
        : payload
          ? `
if (result?.enabled == true) {
    // Do something differently for this user
    println(result.payload)

    // Deserialize the payload into a typed object
    result.getPayloadAs<MyConfig>()?.let { config ->
        println(config)
    }
}`
          : `
if (result?.enabled == true) {
    // Do something differently for this user
}`

    const payloadCode =
        payload && multivariant
            ? `

result?.payload?.let { payload ->
    println(payload)
}

// Deserialize the payload into a typed object
result?.getPayloadAs<MyConfig>()?.let { config ->
    println(config)
}`
            : ''

    return (
        <CodeSnippet language={Language.Kotlin} wrap>
            {`val result = PostHog.getFeatureFlagResult("${flagKey}")${flagCheck}${payloadCode}`}
        </CodeSnippet>
    )
}

export function FlutterSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const flagCheck = multivariant
        ? `
if (result?.variant == 'example-variant') {
  // Do something differently for this user
}`
        : payload
          ? `
if (result?.enabled == true) {
  // Do something differently for this user
  if (result?.payload != null) {
    // result.payload contains the deserialized JSON value (String, num, bool, Map, or List)
  }
}`
          : `
if (result?.enabled == true) {
  // Do something differently for this user
}`

    const payloadCode =
        payload && multivariant
            ? `

if (result?.payload != null) {
  // result.payload contains the deserialized JSON value (String, num, bool, Map, or List)
  // Do something with the payload
}`
            : ''

    return (
        <CodeSnippet language={Language.Dart} wrap>
            {`final result = await Posthog().getFeatureFlagResult('${flagKey}');${flagCheck}${payloadCode}`}
        </CodeSnippet>
    )
}

export function iOSSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const flagCheck = multivariant
        ? `
if result?.variant == "example-variant" {
    // Do something differently for this user
}`
        : payload
          ? `
if result?.enabled == true {
    // Do something differently for this user

    if let payload = result?.payload {
        // result.payload contains a JSON value (String, Int, Bool, Dictionary, or Array)
        print(payload)
    }

    // Otherwise, deserialize the payload into a typed struct
    if let config = result?.payloadAs(MyConfig.self) {
        print(config)
    }
}`
          : `
if result?.enabled == true {
    // Do something differently for this user
}`

    const payloadCode =
        payload && multivariant
            ? `

if let payload = result?.payload {
    // result.payload contains a JSON value (String, Int, Bool, Dictionary, or Array)
    print(payload)
}

// Otherwise, deserialize the payload into a typed struct
if let config = result?.payloadAs(MyConfig.self) {
    print(config)
}`
            : ''

    return (
        <CodeSnippet language={Language.Swift} wrap>
            {`let result = PostHogSDK.shared.getFeatureFlagResult("${flagKey}")${flagCheck}${payloadCode}`}
        </CodeSnippet>
    )
}

export function ReactNativeSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const conditional = multivariant ? `result?.variant === 'example-variant'` : `result?.enabled`

    const payloadCode = payload
        ? `
    if (result?.payload) {
        // result.payload contains a JSON value (string, number, boolean, object, or array)
    }`
        : ''

    return (
        <CodeSnippet language={Language.JSX} wrap>
            {`// With a hook
import { useFeatureFlagResult } from 'posthog-react-native'

function MyComponent() {
    const result = useFeatureFlagResult('${flagKey}')${payloadCode}

    return ${conditional} ? <Text>Testing feature 😄</Text> : <Text>Not testing feature 😢</Text>
}

// Or calling the method directly
const result = posthog.getFeatureFlagResult('${flagKey}')`}
        </CodeSnippet>
    )
}

export function ReactSnippet({ flagKey, multivariant, payload }: FeatureFlagSnippet): JSX.Element {
    const conditional = multivariant ? `result?.variant === 'example-variant'` : `result?.enabled`

    const payloadCode = payload
        ? `
    if (result?.payload) {
        // result.payload contains a JSON value (string, number, boolean, object, or array)
    }`
        : ''

    return (
        <CodeSnippet language={Language.JSX} wrap>
            {`// With a hook
import { useFeatureFlagResult } from '@posthog/react'

function App() {
    const result = useFeatureFlagResult('${flagKey}')${payloadCode}

    return ${conditional} ? <div>Testing feature 😄</div> : <div>Not testing feature 😢</div>
}

// Or calling the method directly
const result = posthog.getFeatureFlagResult('${flagKey}')`}
        </CodeSnippet>
    )
}

export function APISnippet({ flagKey, groupType, remoteConfiguration }: FeatureFlagSnippet): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const groupAddition = groupType
        ? `,
    "groups": { "${groupType.group_type}": "<${groupType.name_singular || 'group'} ID>" },`
        : ''

    if (remoteConfiguration) {
        return (
            <>
                <CodeSnippet language={Language.Bash} wrap>
                    {`curl ${apiHostOrigin()}/api/projects/${currentTeam?.id || ':projectId'}/feature_flags/${
                        flagKey || ':featureFlagKey'
                    }/remote_config/ \\
-H 'Content-Type: application/json' \\
-H 'Authorization: Bearer [personal_api_key]'`}
                </CodeSnippet>
            </>
        )
    }

    return (
        <>
            <CodeSnippet language={Language.Bash} wrap>
                {`curl ${apiHostOrigin()}/flags/?v=2 \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${currentTeam ? currentTeam.api_token : '[project_api_key]'}",
    "distinct_id": "[user distinct id]"${groupAddition}
}'`}
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
    const propertyName = samplePropertyName || 'is_authorized'

    const propertyOverrideSnippet = `// Your flag depends on properties that are not instantly available. If you want
// to make them available without waiting for server delays, send these properties for flag evaluation, like so:
// Make sure to call this before evaluating flags. More info: https://posthog.com/docs/libraries/js/usage#overriding-server-properties
posthog.${
        groupType
            ? `setGroupPropertiesForFlags({ '${groupType.group_type}': {'${propertyName}': 'value'}})`
            : `setPersonPropertiesForFlags({'${propertyName}': 'value'})`
    }

`

    const conditional = multivariant ? `result?.variant === 'example-variant'` : `result?.enabled`

    const buildFlagBody = (baseIndent: string): string => {
        const contentIndent = baseIndent + '    '
        const innerIndent = contentIndent + '    '
        const payloadLine =
            !multivariant && payload
                ? `\n${contentIndent}if (result.payload) {\n${innerIndent}// result.payload contains a JSON value (string, number, boolean, object, or array)\n${contentIndent}}`
                : ''
        return `if (${conditional}) {\n${contentIndent}// Do something differently for this user${payloadLine}\n${baseIndent}}`
    }

    const payloadCode =
        payload && multivariant
            ? `

if (result?.payload) {
    // result.payload contains a JSON value (string, number, boolean, object, or array)
    // Do something with the payload
}`
            : ''

    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`${instantlyAvailableProperties ? '' : propertyOverrideSnippet}// Ensure flags are loaded before usage.
// You'll only need to call this on the code for when the first time a user visits.
posthog.onFeatureFlags(function() {
    // feature flags should be available at this point
    const result = posthog.getFeatureFlagResult('${flagKey ?? ''}')
    ${buildFlagBody('    ')}
})

// Otherwise, you can just do:
const result = posthog.getFeatureFlagResult('${flagKey ?? ''}')
${buildFlagBody('')}${payloadCode}`}
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
})`}
        </CodeSnippet>
    )
}
