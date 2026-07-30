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
                        {dedent`
                            Pass the same \`$ai_session_id\` across every call in a conversation to group them into one
                            session. Pass \`posthog_trace_id\` to group several calls into one trace. The wrapper
                            reports \`$ai_provider\` as \`openai\` by default, so pass it explicitly, as shown above, to
                            attribute cost and usage to ${config.label} instead of OpenAI.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}
