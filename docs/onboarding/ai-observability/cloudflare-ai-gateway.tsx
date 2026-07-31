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
                            Cloudflare AI Gateway exposes an OpenAI-compatible \`compat\` endpoint at
                            \`https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/compat\`. Create a
                            PostHog client, then swap in PostHog's OpenAI wrapper, pointed at this URL.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            Pass your upstream provider key (for example, your OpenAI key) as \`api_key\`, and your
                            AI Gateway token via the \`cf-aig-authorization\` header. The example in the next step
                            creates both, then calls Cloudflare AI Gateway and captures a tool call as a span in one
                            flow.
                        `}
                    </Markdown>
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
                            captures an \`$ai_generation\` event. Specify models as \`provider/model-id\`, for
                            example \`openai/gpt-5-mini\` or \`anthropic/claude-sonnet-4-5\`. The wrapper does not
                            see tools you call afterward. The example below also captures a tool call as an
                            \`$ai_span\` event, right after the generation that triggered it.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            Both events share the same \`$ai_trace_id\`, so they nest in one trace, and the same
                            \`$ai_session_id\`, so they group into the same conversation. \`client\` wraps Cloudflare
                            AI Gateway and captures the generation. \`posthog\` captures the span.
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

                                    session_id = "conversation-abc"  # same across every turn of the conversation
                                    trace_id = str(uuid.uuid4())     # one per turn
                                    distinct_id = "user_123"

                                    # tools and get_weather() are your existing tool-calling setup
                                    response = client.chat.completions.create(
                                        model="openai/gpt-5-mini",
                                        max_completion_tokens=1024,
                                        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                        tools=tools,
                                        posthog_distinct_id=distinct_id,
                                        posthog_trace_id=trace_id,
                                        posthog_properties={"$ai_session_id": session_id, "$ai_provider": "cloudflare"},
                                    )

                                    # Capture each tool call as a span nested under the generation above
                                    for call in response.choices[0].message.tool_calls:
                                        start = time.time()
                                        result = get_weather(**json.loads(call.function.arguments))

                                        posthog.capture(
                                            distinct_id=distinct_id,
                                            event="$ai_span",
                                            properties={
                                                "$ai_trace_id": trace_id,
                                                "$ai_session_id": session_id,
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

                                    const sessionId = 'conversation-abc' // same across every turn of the conversation
                                    const traceId = crypto.randomUUID()  // one per turn
                                    const distinctId = 'user_123'

                                    // tools and getWeather() are your existing tool-calling setup
                                    const response = await client.chat.completions.create({
                                      model: 'openai/gpt-5-mini',
                                      max_completion_tokens: 1024,
                                      messages: [{ role: 'user', content: "What's the weather in Paris?" }],
                                      tools,
                                      posthogDistinctId: distinctId,
                                      posthogTraceId: traceId,
                                      posthogProperties: { $ai_session_id: sessionId, $ai_provider: 'cloudflare' },
                                    })

                                    // Capture each tool call as a span nested under the generation above
                                    for (const call of response.choices[0].message.tool_calls) {
                                      const start = Date.now()
                                      const result = await getWeather(JSON.parse(call.function.arguments))

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
                            \`posthog_distinct_id\` ties this call to a person, so you can see everything one user
                            asked for and know who hit an error or ran up cost. \`$ai_session_id\` groups every call
                            in one conversation, so a multi-turn exchange reads as a single thread instead of
                            separate, unrelated calls. A trace covers one turn, and a session covers the whole
                            conversation: passing the same session id across every turn is what connects them.
                            Together, \`posthog_distinct_id\` and \`$ai_session_id\` give you a complete view: which
                            person, which conversation, which turn, and every LLM call and tool call inside it.
                        `}
                    </Markdown>

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
                            The recommended example above already captures a tool call as a span nested under its
                            generation. The rules below apply whenever you capture a span by hand, including cases
                            with more than one tool.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            The span must carry the same \`$ai_trace_id\` as the generation it belongs to, or it
                            will not nest under the same trace. Nothing measures duration for you: time your own
                            code and pass the result as \`$ai_latency\`. Set \`$ai_span_type\` to describe the kind
                            of work, for example \`tool\`, \`chain\`, \`retriever\`, or \`agent\`.
                        `}
                    </Markdown>

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
