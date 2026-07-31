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

                    <Markdown>
                        Pass the same `$ai_session_id` across every call in a conversation to group them into one
                        session, and `posthog_trace_id` to group several calls into one trace.
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
