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
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-azure-openai)
                            and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-azure-openai)
                            examples on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see
                            the [Node.js
                            wrapper](https://github.com/PostHog/posthog-js/tree/e08ff1be/examples/example-ai-azure-openai)
                            and [Python
                            wrapper](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-azure-openai)
                            examples.
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
                    <Markdown>Create a PostHog client, then swap in PostHog's Azure OpenAI wrapper.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog import Posthog
                                    from posthog.ai.openai import AzureOpenAI

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
                            Now, when you use the wrapped client to call Azure OpenAI, PostHog automatically
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
                                        model="<your-deployment-name>",
                                        messages=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        posthog_distinct_id="user_123",
                                        posthog_properties={"$ai_session_id": "conversation-abc", "$ai_provider": "azure"},
                                    )

                                    print(response.choices[0].message.content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.chat.completions.create({
                                      model: '<your-deployment-name>',
                                      messages: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                      posthogDistinctId: 'user_123',
                                      posthogProperties: { $ai_session_id: 'conversation-abc', $ai_provider: 'azure' },
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
                            session, and \`posthog_trace_id\` to group several calls into one trace. Passing
                            \`$ai_provider\` explicitly, as shown above, ensures cost and usage are attributed
                            correctly instead of defaulting to OpenAI.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const AzureOpenAIInstallation = createInstallation(getAzureOpenAISteps)
