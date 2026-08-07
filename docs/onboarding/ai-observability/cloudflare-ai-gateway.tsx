import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getCloudflareAIGatewaySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="fyi" icon="IconInfo" title="Full working examples">
                        <Markdown>
                            See the complete
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-cloudflare-ai-gateway)
                            and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-cloudflare-ai-gateway)
                            examples on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the PostHog SDK and the OpenAI SDK.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai posthog-node openai
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
                            Create a PostHog client, then swap in PostHog's OpenAI wrapper, pointed at your
                            Cloudflare AI Gateway endpoint.
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
                                    import time, uuid, json

                                    posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                    client = OpenAI(
                                        base_url="https://gateway.ai.cloudflare.com/v1/<account_id>/<gateway_id>/compat",
                                        api_key="<openai_api_key>",
                                        default_headers={
                                            "cf-aig-authorization": "Bearer <cf_aig_token>",
                                        },
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

                                    const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                                    const client = new OpenAI({
                                      baseURL: 'https://gateway.ai.cloudflare.com/v1/<account_id>/<gateway_id>/compat',
                                      apiKey: '<openai_api_key>',
                                      defaultHeaders: {
                                        'cf-aig-authorization': 'Bearer <cf_aig_token>',
                                      },
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
            title: 'Call Cloudflare AI Gateway',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            When you use the wrapped client to call Cloudflare AI Gateway, PostHog automatically
                            captures an \`$ai_generation\` event.
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
                                        model="openai/gpt-5-mini",
                                        max_completion_tokens=1024,
                                        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                        tools=tools,
                                        posthog_distinct_id="user_123",
                                        posthog_trace_id=trace_id,
                                        posthog_properties={
                                            "$ai_session_id": "conversation-abc",
                                            "$ai_provider": "cloudflare",
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
                                      model: 'openai/gpt-5-mini',
                                      max_completion_tokens: 1024,
                                      messages: [{ role: 'user', content: "What's the weather in Paris?" }],
                                      tools,
                                      posthogDistinctId: 'user_123',
                                      posthogTraceId: traceId,
                                      posthogProperties: {
                                        $ai_session_id: 'conversation-abc',
                                        $ai_provider: 'cloudflare',
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
                                        distinctId,
                                        event: '$ai_span',
                                        properties: {
                                          $ai_trace_id: traceId,
                                          $ai_session_id: sessionId,
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

export const CloudflareAIGatewayInstallation = createInstallation(getCloudflareAIGatewaySteps)
