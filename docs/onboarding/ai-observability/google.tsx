import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getGoogleSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-gemini) and
                            [Python](https://github.com/PostHog/posthog-python/tree/main/examples/example-ai-gemini)
                            examples on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the PostHog SDK and the Google Gen AI SDK.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog google-genai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai posthog-node @google/genai
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
                    <Markdown>Create a PostHog client, then swap in PostHog's Google Gen AI wrapper.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog import Posthog
                                    from posthog.ai.gemini import Client

                                    posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                    client = Client(
                                        api_key="your_gemini_api_key",
                                        posthog_client=posthog,
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { GoogleGenAI } from '@posthog/ai/gemini'
                                    import { PostHog } from 'posthog-node'

                                    const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                                    const client = new GoogleGenAI({
                                      apiKey: 'your_gemini_api_key',
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
            title: 'Call Google Gen AI LLMs',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Now, when you use the wrapped client to call Gemini, PostHog automatically captures
                        `$ai_generation` events.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=[{"role": "user", "parts": [{"text": "Tell me a fun fact about hedgehogs"}]}],
                                        posthog_distinct_id="user_123",
                                        posthog_properties={"$ai_session_id": "conversation-abc"},
                                    )

                                    print(response.text)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.models.generateContent({
                                      model: 'gemini-2.5-flash',
                                      contents: 'Tell me a fun fact about hedgehogs',
                                      posthogDistinctId: 'user_123',
                                      posthogProperties: { $ai_session_id: 'conversation-abc' },
                                    })

                                    console.log(response.text)
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            {dedent`
                                **Note:** This integration also works with Vertex AI via Google Cloud Platform. Initialize the Google Gen AI client with \`vertexai=True, project=..., location=...\` (Python) or \`{ vertexai: true, project: '...', location: '...' }\` (Node) and the PostHog wrapper will capture those calls the same way.
                            `}
                        </Markdown>
                    </Blockquote>

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
                            \`$ai_session_id\`, so they group into the same conversation. \`client\` is the Google
                            Gen AI wrapper configured above, which captures the \`$ai_generation\` automatically.
                            \`posthog\` is the raw client used to capture the span. Gemini lists requested calls on
                            \`response.function_calls\`, and each call's \`args\` is already a parsed object, so
                            there's no JSON string to decode.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    import time, uuid
                                    from google.genai import types

                                    session_id = "conversation-abc"  # same across every turn of the conversation
                                    trace_id = str(uuid.uuid4())     # one per turn
                                    distinct_id = "user_123"

                                    # tools and get_weather() are your existing tool-calling setup
                                    response = client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=[{"role": "user", "parts": [{"text": "What's the weather in Paris?"}]}],
                                        config=types.GenerateContentConfig(tools=tools),
                                        posthog_distinct_id=distinct_id,
                                        posthog_trace_id=trace_id,
                                        posthog_properties={"$ai_session_id": session_id},
                                    )

                                    # Capture each function call as a span nested under the generation above
                                    for call in response.function_calls or []:
                                        start = time.time()
                                        result = get_weather(**call.args)

                                        posthog.capture(
                                            distinct_id=distinct_id,
                                            event="$ai_span",
                                            properties={
                                                "$ai_trace_id": trace_id,
                                                "$ai_session_id": session_id,
                                                "$ai_span_id": str(uuid.uuid4()),
                                                "$ai_span_name": call.name,
                                                "$ai_input_state": call.args,
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
                                    const response = await client.models.generateContent({
                                      model: 'gemini-2.5-flash',
                                      contents: "What's the weather in Paris?",
                                      config: { tools },
                                      posthogDistinctId: distinctId,
                                      posthogTraceId: traceId,
                                      posthogProperties: { $ai_session_id: sessionId },
                                    })

                                    // Capture each function call as a span nested under the generation above
                                    for (const call of response.functionCalls ?? []) {
                                      const start = Date.now()
                                      const result = await getWeather(call.args)

                                      posthog.capture({
                                        distinctId,
                                        event: '$ai_span',
                                        properties: {
                                          $ai_trace_id: traceId,
                                          $ai_session_id: sessionId,
                                          $ai_span_id: crypto.randomUUID(),
                                          $ai_span_name: call.name,
                                          $ai_input_state: call.args,
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
        {
            title: 'Capture embeddings',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        PostHog can also capture embedding generations as `$ai_embedding` events. The wrapped client
                        captures these automatically when you use the `embed_content` API:
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.models.embed_content(
                                        model="gemini-embedding-001",
                                        contents="The quick brown fox",
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.models.embedContent({
                                      model: 'gemini-embedding-001',
                                      contents: 'The quick brown fox',
                                    })
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const GoogleInstallation = createInstallation(getGoogleSteps)
