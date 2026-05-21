import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

function ServerSideWarning(): JSX.Element {
    return (
        <div className="warning">
            <p>
                <b>Warning:</b> Server side experiment metrics require you to manually send the feature flag
                information.{' '}
                <Link to="https://posthog.com/docs/experiments/adding-experiment-code" target="_blank">
                    See this tutorial for more information.
                </Link>
            </p>
        </div>
    )
}

interface SnippetProps {
    flagKey: string
    variant: string
}

export function AndroidSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Kotlin} wrap>
                {`if (PostHog.getFeatureFlag("${flagKey}") == "${variant}") {
    // do something
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
        </>
    )
}

export function IOSSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Swift} wrap>
                {`if (PostHogSDK.shared.getFeatureFlag("${flagKey}") as? String == "${variant}") {
    // do something
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
        </>
    )
}

export function NodeJSSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`const experimentFlagValue = await client.getFeatureFlag('${flagKey}', 'user distinct id')

if (experimentFlagValue === '${variant}' ) {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function JSSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <div>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.getFeatureFlag('${flagKey}') === '${variant}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <div className="mt-4 mb-1">
                <b>Test that it works</b>
            </div>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`posthog.featureFlags.overrideFeatureFlags({ flags: {'${flagKey}': '${variant}'} })`}
            </CodeSnippet>
        </div>
    )
}

export function ReactSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`// You can either use the useFeatureFlagVariantKey hook,
// or you can use the feature flags component - https://posthog.com/docs/libraries/react#feature-flags-react-component

// Method one: using the useFeatureFlagVariantKey hook
import { useFeatureFlagVariantKey } from '@posthog/react'

function App() {
    const variant = useFeatureFlagVariantKey('${flagKey}')
    if (variant === '${variant}') {
        // do something
    }
}

// Method two: using the feature flags component
import { PostHogFeature } from '@posthog/react'

function App() {
    return (
        <PostHogFeature flag='${flagKey}' match='${variant}'>
            <div>
                {/* the component to show */}
            </div>
        </PostHogFeature>
    )
}

// You can also test your code by overriding the feature flag:
posthog.featureFlags.overrideFeatureFlags({ flags: {'${flagKey}': '${variant}'} })`}
            </CodeSnippet>
        </>
    )
}

export function RNSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.getFeatureFlag('${flagKey}') === '${variant}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
        </>
    )
}

export function PHPSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.PHP} wrap>
                {`if (PostHog::getFeatureFlag('${flagKey}', 'user distinct id') == '${variant}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function GolangSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Go} wrap>
                {`experimentFlagValue, err := client.GetFeatureFlag(posthog.FeatureFlagPayload{
    Key:        '${flagKey}',
    DistinctId: "distinct-id",
})
if err != nil {
    // Handle error (e.g. capture error and fallback to default behaviour)
}
if experimentFlagValue == '${variant}' {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function FlutterSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    const clientSuffix = 'await Posthog().'
    const flagFunction = 'getFeatureFlag'
    const variantSuffix = ` == '${variant}'`

    return (
        <>
            <CodeSnippet language={Language.Dart} wrap>
                {`if (${clientSuffix}${flagFunction}('${flagKey}')${variantSuffix}) {
  // Do something differently for this user
} else {
  // It's a good idea to let control variant always be the default behaviour,
  // so if something goes wrong with flag evaluation, you don't break your app.
}
            `}
            </CodeSnippet>
        </>
    )
}

export function RubySnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Ruby} wrap>
                {`experimentFlagValue = posthog.get_feature_flag('${flagKey}', 'user distinct id')


if experimentFlagValue == '${variant}'
    # Do something differently for this user
else
    # It's a good idea to let control variant always be the default behaviour,
    # so if something goes wrong with flag evaluation, you don't break your app.
end
`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function PythonSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`experiment_flag_value = posthog.get_feature_flag("${flagKey}", "user_distinct_id"):

if experiment_flag_value == '${variant}':
    # Do something differently for this user
else:
    # It's a good idea to let control variant always be the default behaviour,
    # so if something goes wrong with flag evaluation, you don't break your app.
`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export function JavaSnippet({ flagKey, variant }: SnippetProps): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Java} wrap>
                {`Object flagValue = postHog.getFeatureFlag("user distinct id", "${flagKey}");
if ("${variant}".equals(flagValue)) {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}
`}
            </CodeSnippet>
            <ServerSideWarning />
        </>
    )
}

export interface PromptSnippetProps {
    flagKey: string
}

export function PromptExperimentPythonSnippet({ flagKey }: PromptSnippetProps): JSX.Element {
    return (
        <CodeSnippet language={Language.Python} wrap>
            {`import json
import os

from posthog import Posthog
from posthog.ai.openai import OpenAI
from posthog.ai.prompts import Prompts

posthog = Posthog(
    os.environ["POSTHOG_API_KEY"],
    host="https://us.posthog.com",  # Replace with your PostHog host (e.g. https://eu.posthog.com for EU Cloud, or your self-hosted URL)
    personal_api_key=os.environ["POSTHOG_PERSONAL_API_KEY"],
)

distinct_id = "<your-user-id>"
flag_key = "${flagKey}"

# 1. Evaluate the flag and pull the variant payload — each variant carries its own
#    {"prompt_name", "prompt_version"} payload set when the experiment was created.
#    send_feature_flag_events=True emits the $feature_flag_called exposure event the
#    experiment metric joins against — without it the results page stays blank.
payload = posthog.get_feature_flag_payload(flag_key, distinct_id, send_feature_flag_events=True)
if not payload:
    raise RuntimeError(f"No payload set for flag {flag_key}; was this experiment created via /create_from_prompt/?")
if isinstance(payload, str):
    payload = json.loads(payload)

prompt_name = payload["prompt_name"]
prompt_version = int(payload["prompt_version"])

# 2. Fetch and compile the prompt
prompts = Prompts(posthog)
prompt = prompts.get(prompt_name, version=prompt_version)
system_prompt = prompts.compile(prompt, {})

# 3. Call the LLM — the wrapper auto-emits $ai_generation
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], posthog_client=posthog)
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "system", "content": system_prompt}],
    posthog_distinct_id=distinct_id,
    posthog_properties={
        "$ai_prompt_name": prompt_name,
        "$ai_prompt_version": prompt_version,
    },
)

print(response.choices[0].message.content)
`}
        </CodeSnippet>
    )
}

export function PromptExperimentJSSnippet({ flagKey }: PromptSnippetProps): JSX.Element {
    return (
        <CodeSnippet language={Language.TypeScript} wrap>
            {`import { PostHog } from 'posthog-node'
import { OpenAI } from '@posthog/ai/openai'
import { Prompts } from '@posthog/ai/prompts'

const posthog = new PostHog(process.env.POSTHOG_API_KEY!, {
    host: 'https://us.posthog.com', // Replace with your PostHog host (e.g. https://eu.posthog.com for EU Cloud, or your self-hosted URL)
    personalApiKey: process.env.POSTHOG_PERSONAL_API_KEY,
})

const distinctId = '<your-user-id>'
const flagKey = '${flagKey}'

// 1. Evaluate the flag and read the variant payload — each variant carries its own
//    { prompt_name, prompt_version } payload set when the experiment was created.
//    getFeatureFlagResult emits the $feature_flag_called exposure event the experiment
//    metric joins against — without it the results page stays blank.
const result = await posthog.getFeatureFlagResult(flagKey, distinctId)
let payload = result?.payload
if (!payload) {
    throw new Error(\`No payload set for flag \${flagKey}; was this experiment created via /create_from_prompt/?\`)
}
if (typeof payload === 'string') {
    payload = JSON.parse(payload)
}

const promptName: string = payload.prompt_name
const promptVersion: number = Number(payload.prompt_version)

// 2. Fetch and compile the prompt
const prompts = new Prompts(posthog)
const prompt = await prompts.get(promptName, { version: promptVersion })
const systemPrompt = prompts.compile(prompt, {})

// 3. Call the LLM — the wrapper auto-emits $ai_generation
const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY!, posthog })
const response = await client.chat.completions.create({
    model: 'gpt-4o-mini',
    messages: [{ role: 'system', content: systemPrompt }],
    posthogDistinctId: distinctId,
    posthogProperties: {
        $ai_prompt_name: promptName,
        $ai_prompt_version: promptVersion,
    },
})

console.log(response.choices[0].message.content)
`}
        </CodeSnippet>
    )
}

export function PromptExperimentAgentPromptSnippet({ flagKey }: PromptSnippetProps): JSX.Element {
    return (
        <CodeSnippet language={Language.Text} wrap>
            {`Wire up a PostHog prompt experiment in this project.

Context
- A feature flag with key "${flagKey}" controls variant assignment for this experiment.
- Each variant's payload is JSON of shape { "prompt_name": string, "prompt_version": number }.
- The experiment's metric filters events on the $ai_prompt_name property — every LLM
  generation event MUST include $ai_prompt_name for the experiment to attribute it.

What to do
1. Detect the language and framework from existing project files. Use the PostHog SDK
   that matches (posthog-python, posthog-node, etc.). Check the existing package manifest
   before installing a new SDK.
2. Make sure POSTHOG_API_KEY, POSTHOG_PERSONAL_API_KEY, and the LLM provider's API key
   (e.g. OPENAI_API_KEY) are loaded from env. Add to .env / env example if missing,
   following the project's existing env conventions.
3. Find where the project makes LLM calls (route handler, service module, agent loop,
   background job — match the existing structure). For each LLM call, before invoking
   the model:
   a) Evaluate the feature flag "${flagKey}" for the current user, and make sure the
      evaluation call also emits the $feature_flag_called exposure event (e.g. via
      posthog.get_feature_flag_payload(..., send_feature_flag_events=True) in Python or
      posthog.getFeatureFlagResult(...) in Node — without this event the experiment
      metric has nothing to join the $ai_generation events against and the results
      page stays blank).
   b) Read the variant's payload from the evaluation result. Parse JSON if it returns
      a string. Extract prompt_name and prompt_version.
   c) Use PostHog's prompt management API to fetch the prompt by name + version, then
      compile it. Pass the compiled prompt as the system message.
   d) Wrap the LLM client with PostHog's AI tracing wrapper (e.g. @posthog/ai for
      Node, posthog.ai for Python) so $ai_generation events are auto-emitted with
      cost, latency, and tokens.
   e) Pass posthog_distinct_id / posthogDistinctId and attach event properties:
      $ai_prompt_name = prompt_name and $ai_prompt_version = prompt_version. The
      $ai_prompt_name property is REQUIRED — this is how the experiment metric
      attributes events to this prompt.
4. Do NOT also call posthog.capture('$ai_generation', ...) — the wrapper already emits
   it. Double-capturing inflates metrics.

Constraints
- Follow conventions already established in this project (framework, config layout,
  testing patterns, error handling). Don't introduce new frameworks or invent config.
- Verify SDK names and method signatures against the docs below before generating code;
  the SDK surface evolves.

Reference docs
- AI observability overview:     https://posthog.com/docs/ai-observability
- Prompt management:             https://posthog.com/docs/prompt-management
- Feature flag payloads:         https://posthog.com/docs/feature-flags/payloads
- Experiments:                   https://posthog.com/docs/experiments
- PostHog AI wrappers (OpenAI, Anthropic, Gemini): https://posthog.com/docs/ai-engineering
`}
        </CodeSnippet>
    )
}
