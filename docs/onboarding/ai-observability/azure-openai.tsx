import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAzureOpenAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            [Node.js](https://github.com/PostHog/posthog-js/tree/e08ff1be/examples/example-ai-azure-openai)
                            and
                            [Python](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-azure-openai)
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
                            Create a PostHog client, then swap in PostHog's Azure OpenAI wrapper.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog import Posthog
                                    from posthog.ai.openai import AzureOpenAI
                                    import time, uuid, json

                                    posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                    client = AzureOpenAI(
                                        api_key="<azure_openai_api_key>",
                                        api_version="2024-10-21",
                                        azure_endpoint="https://<your-resource>.openai.azure.com",
                                        posthog_client=posthog,
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { AzureOpenAI } from '@posthog/ai/openai'
                                    import { PostHog } from 'posthog-node'

                                    const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                                    const client = new AzureOpenAI({
                                      apiKey: '<azure_openai_api_key>',
                                      apiVersion: '2024-10-21',
                                      endpoint: 'https://<your-resource>.openai.azure.com',
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
            title: 'Call Azure OpenAI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            When you use the wrapped client to call Azure OpenAI, PostHog automatically captures an
                            \`$ai_generation\` event.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    session_id = "conversation-abc"  # same across every turn of the conversation
                                    trace_id = str(uuid.uuid4())     # one per turn
                                    distinct_id = "user_123"

                                    # tools and get_weather() are your existing tool-calling setup
                                    response = client.chat.completions.create(
                                        model="<your-deployment-name>",
                                        messages=[{"role": "user", "content": "What's the weather in Paris?"}],
                                        tools=tools,
                                        posthog_distinct_id=distinct_id,
                                        posthog_trace_id=trace_id,
                                        posthog_properties={"$ai_session_id": session_id, "$ai_provider": "azure"},
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
                                      model: '<your-deployment-name>',
                                      messages: [{ role: 'user', content: "What's the weather in Paris?" }],
                                      tools,
                                      posthogDistinctId: distinctId,
                                      posthogTraceId: traceId,
                                      posthogProperties: { $ai_session_id: sessionId, $ai_provider: 'azure' },
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
                                    # Capture each tool call as a span nested under the generation above
                                    for call in response.choices[0].message.tool_calls or []:
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
                                    // Capture each tool call as a span nested under the generation above
                                    for (const call of response.choices[0].message.tool_calls ?? []) {
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
                            See [spans](https://posthog.com/docs/ai-observability/spans) for the full list of span
                            properties.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const AzureOpenAIInstallation = createInstallation(getAzureOpenAISteps)
