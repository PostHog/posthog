import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getPortkeySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="info" icon="IconInfo" title="Full working examples">
                        <Markdown>
                            See the complete
                            [Node.js](https://github.com/PostHog/posthog-js/tree/e08ff1be/examples/example-ai-portkey)
                            and
                            [Python](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-portkey)
                            examples on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the PostHog SDK, the OpenAI SDK, and the Portkey SDK.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog openai portkey-ai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai posthog-node openai portkey-ai
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Create a PostHog client, then swap in PostHog's OpenAI wrapper, pointed at Portkey's
                            gateway URL.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog import Posthog
                                    from posthog.ai.openai import OpenAI
                                    from portkey_ai import PORTKEY_GATEWAY_URL
                                    import time, uuid, json

                                    posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                    client = OpenAI(
                                        base_url=PORTKEY_GATEWAY_URL,
                                        api_key="<portkey_api_key>",
                                        posthog_client=posthog,
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { OpenAI } from '@posthog/ai/openai'
                                    import { PostHog } from 'posthog-node'
                                    import { PORTKEY_GATEWAY_URL } from 'portkey-ai'

                                    const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                                    const client = new OpenAI({
                                      baseURL: PORTKEY_GATEWAY_URL,
                                      apiKey: '<portkey_api_key>',
                                      posthog,
                                    })
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Call Portkey',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            When you use the wrapped client to call Portkey, PostHog automatically captures an
                            \`$ai_generation\` event.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    trace_id = str(uuid.uuid4())

                                    response = client.chat.completions.create(
                                        model="@<integration-slug>/gpt-5-mini",
                                        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                        tools=tools,
                                        posthog_distinct_id="user_123",
                                        posthog_trace_id=trace_id,
                                        posthog_properties={
                                            "$ai_session_id": "conversation-abc",
                                            "$ai_provider": "portkey",
                                        },
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const traceId = crypto.randomUUID()

                                    const response = await client.chat.completions.create({
                                      model: '@<integration-slug>/gpt-5-mini',
                                      messages: [{ role: 'user', content: "What's the weather in Paris?" }],
                                      tools,
                                      posthogDistinctId: 'user_123',
                                      posthogTraceId: traceId,
                                      posthogProperties: {
                                        $ai_session_id: 'conversation-abc',
                                        $ai_provider: 'portkey',
                                      },
                                    })
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit `posthog_distinct_id` from the
                            call. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>

                    <Markdown>
                        {dedent`
                            You can expect captured \`$ai_generation\` events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
        {
            title: 'Capture tool calls as spans',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For standard responses, the posthog client captures it as a generation. For all tool
                            calls, you must manually capture them as \`$ai_span\` events.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    for call in response.choices[0].message.tool_calls or []:
                                        start = time.time()
                                        result = run_tool(call.function.name, json.loads(call.function.arguments))

                                        posthog.capture(
                                            distinct_id="user_123",
                                            event="$ai_span",
                                            properties={
                                                "$ai_trace_id": trace_id,
                                                "$ai_session_id": "conversation-abc",
                                                "$ai_span_id": str(uuid.uuid4()),
                                                "$ai_span_name": call.function.name,
                                                "$ai_input_state": call.function.arguments,
                                                "$ai_output_state": result,
                                                "$ai_latency": time.time() - start,
                                            },
                                        )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    for (const call of response.choices[0].message.tool_calls ?? []) {
                                      const start = Date.now()
                                      const result = await runTool(call.function.name, JSON.parse(call.function.arguments))

                                      posthog.capture({
                                        distinctId: 'user_123',
                                        event: '$ai_span',
                                        properties: {
                                          $ai_trace_id: traceId,
                                          $ai_session_id: 'conversation-abc',
                                          $ai_span_id: crypto.randomUUID(),
                                          $ai_span_name: call.function.name,
                                          $ai_input_state: call.function.arguments,
                                          $ai_output_state: result,
                                          $ai_latency: (Date.now() - start) / 1000,
                                        },
                                      })
                                    }
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            See [spans](https://posthog.com/docs/ai-observability/spans) for the full list of span
                            properties.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const PortkeyInstallation = createInstallation(getPortkeySteps)
