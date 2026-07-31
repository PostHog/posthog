import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAnthropicSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-anthropic) and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-anthropic)
                            examples on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the PostHog SDK and the Anthropic SDK.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog anthropic
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai posthog-node @anthropic-ai/sdk
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
                    <Markdown>Create a PostHog client, then swap in PostHog's Anthropic wrapper.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog import Posthog
                                    from posthog.ai.anthropic import Anthropic

                                    posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                    client = Anthropic(
                                        api_key="sk-ant-api...",
                                        posthog_client=posthog,
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { Anthropic } from '@posthog/ai/anthropic'
                                    import { PostHog } from 'posthog-node'

                                    const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                                    const client = new Anthropic({
                                      apiKey: 'sk-ant-api...',
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
            title: 'Call Anthropic',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Now, when you use the wrapped client to call Anthropic, PostHog automatically captures
                        `$ai_generation` events.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.messages.create(
                                        model="claude-sonnet-4-20250514",
                                        max_tokens=1024,
                                        messages=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        posthog_distinct_id="user_123",
                                        posthog_properties={"$ai_session_id": "conversation-abc"},
                                    )

                                    print(response.content[0].text)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.messages.create({
                                      model: 'claude-sonnet-4-20250514',
                                      max_tokens: 1024,
                                      messages: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                      posthogDistinctId: 'user_123',
                                      posthogProperties: { $ai_session_id: 'conversation-abc' },
                                    })

                                    console.log(response.content[0].text)
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** On Python, this also works with the `AsyncAnthropic` client, as well as
                            `AnthropicBedrock`, `AnthropicVertex`, and the async versions of those — all available from
                            `posthog.ai.anthropic`. The Node wrapper covers the base `Anthropic` client.
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
    ]
}

export const AnthropicInstallation = createInstallation(getAnthropicSteps)
