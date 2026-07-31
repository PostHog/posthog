import { OnboardingComponentsContext } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../../steps'

export interface OpenAICompatibleConfig {
    /** Display name, e.g. 'DeepSeek' */
    label: string
    /** Example-repo slug, e.g. 'deepseek' */
    slug: string
    /** e.g. 'https://api.deepseek.com' */
    baseUrl: string
    /** e.g. '<deepseek_api_key>' */
    apiKeyPlaceholder: string
    /** e.g. 'deepseek-chat' */
    defaultModel: string
}

export const getOpenAICompatibleSteps = (
    ctx: OnboardingComponentsContext,
    config: OpenAICompatibleConfig
): StepDefinition[] => {
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
                            {dedent`
                                See the complete
                                [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-${config.slug}) and
                                [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-${config.slug})
                                examples on GitHub.
                            `}
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
                            Create a PostHog client, then swap in PostHog's OpenAI wrapper, pointed at
                            ${config.label}.
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

                                    posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                    client = OpenAI(
                                        base_url="${config.baseUrl}",
                                        api_key="${config.apiKeyPlaceholder}",
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
                                      baseURL: '${config.baseUrl}',
                                      apiKey: '${config.apiKeyPlaceholder}',
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
            title: `Call ${config.label}`,
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Now, when you use the wrapped client to call ${config.label}, PostHog automatically
                            captures \`$ai_generation\` events.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.chat.completions.create(
                                        model="${config.defaultModel}",
                                        messages=[{"role": "user", "content": "Tell me a fun fact about hedgehogs"}],
                                        posthog_distinct_id="user_123",
                                        posthog_properties={"$ai_session_id": "conversation-abc", "$ai_provider": "${config.slug}"},
                                    )

                                    print(response.choices[0].message.content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.chat.completions.create({
                                      model: '${config.defaultModel}',
                                      messages: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                      posthogDistinctId: 'user_123',
                                      posthogProperties: { $ai_session_id: 'conversation-abc', $ai_provider: '${config.slug}' },
                                    })

                                    console.log(response.choices[0].message.content)
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
                            The wrapper above captures the \`$ai_generation\` event for the LLM call, but it never
                            sees the tools you call after that. A tool call stays invisible unless you capture it
                            yourself, as an \`$ai_span\` event.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            Here's a tool call captured as a span right after the generation that triggered it. Both
                            share the same \`$ai_trace_id\`, so they nest in one trace, and the same
                            \`$ai_session_id\`, so they group into the same conversation. \`client\` is the wrapper
                            configured above, which captures the \`$ai_generation\` automatically. \`posthog\` is the
                            raw client used to capture the span.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import time, uuid, json

                                    session_id = "conversation-abc"  # same across every turn of the conversation
                                    trace_id = str(uuid.uuid4())     # one per turn
                                    distinct_id = "user_123"

                                    # tools and get_weather() are your existing tool-calling setup
                                    response = client.chat.completions.create(
                                        model="${config.defaultModel}",
                                        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                        tools=tools,
                                        posthog_distinct_id=distinct_id,
                                        posthog_trace_id=trace_id,
                                        posthog_properties={"$ai_session_id": session_id},
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
                                    const sessionId = 'conversation-abc' // same across every turn of the conversation
                                    const traceId = crypto.randomUUID()  // one per turn
                                    const distinctId = 'user_123'

                                    // tools and getWeather() are your existing tool-calling setup
                                    const response = await client.chat.completions.create({
                                      model: '${config.defaultModel}',
                                      messages: [{ role: 'user', content: "What's the weather in Paris?" }],
                                      tools,
                                      posthogDistinctId: distinctId,
                                      posthogTraceId: traceId,
                                      posthogProperties: { $ai_session_id: sessionId },
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
                            The span must carry the same \`$ai_trace_id\` as the generation it belongs to, or it
                            won't nest under the same trace. Nothing measures duration for you: time your own code
                            and pass the result as \`$ai_latency\`. Set \`$ai_span_type\` to describe the kind of
                            work, for example \`tool\`, \`chain\`, \`retriever\`, or \`agent\`.
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
