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
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-portkey) and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-portkey)
                            examples on GitHub. If you're using the PostHog SDK wrapper instead of OpenTelemetry, see
                            the [Node.js
                            wrapper](https://github.com/PostHog/posthog-js/tree/e08ff1be/examples/example-ai-portkey)
                            and [Python
                            wrapper](https://github.com/PostHog/posthog-python/tree/7223c52/examples/example-ai-portkey)
                            examples.
                        </Markdown>
                    </CalloutBox>

                    <CalloutBox type="fyi" icon="IconInfo" title="About Portkey">
                        <Markdown>
                            Portkey acts as an AI gateway that routes requests to 250+ LLM providers. The model string
                            format (`@integration-slug/model`) determines which provider to use, where the slug is the
                            name you chose when setting up the integration in Portkey.
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
                        Create a PostHog client, then swap in PostHog's OpenAI wrapper, pointed at Portkey's gateway
                        URL.
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
                            Now, when you use the wrapped client to call Portkey, PostHog automatically captures
                            \`$ai_generation\` events.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.chat.completions.create(
                                        model="@<integration-slug>/gpt-5-mini",
                                        messages=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        posthog_distinct_id="user_123",
                                        posthog_properties={"$ai_session_id": "conversation-abc", "$ai_provider": "portkey"},
                                    )

                                    print(response.choices[0].message.content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.chat.completions.create({
                                      model: '@<integration-slug>/gpt-5-mini',
                                      messages: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                      posthogDistinctId: 'user_123',
                                      posthogProperties: { $ai_session_id: 'conversation-abc', $ai_provider: 'portkey' },
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

export const PortkeyInstallation = createInstallation(getPortkeySteps)
