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
                            PostHog client, then swap in PostHog's OpenAI wrapper, pointed at this URL with your
                            upstream provider key (e.g. your OpenAI key) and your AI Gateway token passed via the
                            \`cf-aig-authorization\` header.
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
                            Now, when you use the wrapped client to call Cloudflare AI Gateway, PostHog
                            automatically captures \`$ai_generation\` events. Specify models as
                            \`provider/model-id\` (for example \`openai/gpt-5-mini\` or
                            \`anthropic/claude-sonnet-4-5\`).
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    response = client.chat.completions.create(
                                        model="openai/gpt-5-mini",
                                        max_completion_tokens=1024,
                                        messages=[
                                            {"role": "user", "content": "Tell me a fun fact about hedgehogs"}
                                        ],
                                        posthog_distinct_id="user_123",
                                        posthog_properties={"$ai_session_id": "conversation-abc", "$ai_provider": "cloudflare"},
                                    )

                                    print(response.choices[0].message.content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    const response = await client.chat.completions.create({
                                      model: 'openai/gpt-5-mini',
                                      max_completion_tokens: 1024,
                                      messages: [{ role: 'user', content: 'Tell me a fun fact about hedgehogs' }],
                                      posthogDistinctId: 'user_123',
                                      posthogProperties: { $ai_session_id: 'conversation-abc', $ai_provider: 'cloudflare' },
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

export const CloudflareAIGatewayInstallation = createInstallation(getCloudflareAIGatewaySteps)
