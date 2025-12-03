import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const AnthropicInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, CalloutBox, ProductScreenshot, OSButton, Markdown, Blockquote, dedent, snippets } =
        useMDXComponents()

    const NotableGenerationProperties = snippets?.NotableGenerationProperties
    return (
        <Steps>
            <Step title="Install the PostHog SDK" badge="required">
                <Markdown>
                    Setting up analytics starts with installing the PostHog SDK for your language. LLM analytics works
                    best with our Python and Node SDKs.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Python',
                            code: dedent`
                                pip install posthog
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'Node',
                            code: dedent`
                                npm install @posthog/ai posthog-node
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Install the Anthropic SDK" badge="required">
                <Markdown>
                    Install the Anthropic SDK. The PostHog SDK instruments your LLM calls by wrapping the Anthropic client.
                    The PostHog SDK **does not** proxy your calls.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Python',
                            code: dedent`
                                pip install anthropic
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'Node',
                            code: dedent`
                                npm install @anthropic-ai/sdk
                            `,
                        },
                    ]}
                />

                <CalloutBox type="fyi" icon="IconInfo" title="Proxy note">
                    <Markdown>
                        These SDKs **do not** proxy your calls. They only fire off an async call to PostHog in the
                        background to send the data. You can also use LLM analytics with other SDKs or our API, but you
                        will need to capture the data in the right format. See the schema in the [manual capture
                        section](https://posthog.com/docs/llm-analytics/installation/manual-capture) for more details.
                    </Markdown>
                </CalloutBox>
            </Step>

            <Step title="Initialize PostHog and the Anthropic wrapper" badge="required">
                <Markdown>
                    Initialize PostHog with your project API key and host from [your project
                    settings](https://app.posthog.com/settings/project), then pass it to our Anthropic wrapper.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                from posthog.ai.anthropic import Anthropic
                                from posthog import Posthog

                                posthog = Posthog(
                                    "<ph_project_api_key>",
                                    host="<ph_client_api_host>"
                                )

                                client = Anthropic(
                                    api_key="sk-ant-api...", # Replace with your Anthropic API key
                                    posthog_client=posthog # This is an optional parameter. If it is not provided, a default client will be used.
                                )
                            `,
                        },
                        {
                            language: 'ts',
                            file: 'Node',
                            code: dedent`
                                import { Anthropic } from '@posthog/ai'
                                import { PostHog } from 'posthog-node'

                                const phClient = new PostHog(
                                  '<ph_project_api_key>',
                                  { host: '<ph_client_api_host>' }
                                )

                                const client = new Anthropic({
                                  apiKey: 'sk-ant-api...', // Replace with your Anthropic API key
                                  posthog: phClient
                                })
                            `,
                        },
                    ]}
                />

                <Blockquote>
                    <Markdown>
                        **Note:** This also works with the `AsyncAnthropic` client as well as `AnthropicBedrock`,
                        `AnthropicVertex`, and the async versions of those.
                    </Markdown>
                </Blockquote>
            </Step>

            <Step title="Call Anthropic LLMs" badge="required">
                <Markdown>
                    Now, when you use the Anthropic SDK to call LLMs, PostHog automatically captures an `$ai_generation`
                    event. You can enrich the event with additional data such as the trace ID, distinct ID, custom
                    properties, groups, and privacy mode options.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                response = client.messages.create(
                                    model="claude-3-opus-20240229",
                                    messages=[
                                        {
                                            "role": "user",
                                            "content": "Tell me a fun fact about hedgehogs"
                                        }
                                    ],
                                    posthog_distinct_id="user_123", # optional
                                    posthog_trace_id="trace_123", # optional
                                    posthog_properties={"conversation_id": "abc123", "paid": True}, # optional
                                    posthog_groups={"company": "company_id_in_your_db"},  # optional
                                    posthog_privacy_mode=False # optional
                                )

                                print(response.content[0].text)
                            `,
                        },
                        {
                            language: 'ts',
                            file: 'Node',
                            code: dedent`
                                const response = await client.messages.create({
                                  model: "claude-3-5-sonnet-latest",
                                  messages: [
                                    {
                                      role: "user",
                                      content: "Tell me a fun fact about hedgehogs"
                                    }
                                  ],
                                  posthogDistinctId: "user_123", // optional
                                  posthogTraceId: "trace_123", // optional
                                  posthogProperties: { conversationId: "abc123", paid: true }, // optional
                                  posthogGroups: { company: "company_id_in_your_db" }, // optional
                                  posthogPrivacyMode: false // optional
                                })

                                console.log(response.content[0].text)
                                phClient.shutdown()
                            `,
                        },
                    ]}
                />

                <Blockquote>
                    <Markdown>
                        {dedent`
                        **Notes:**
                        - This also works when message streams are used (e.g. \`stream=True\` or \`client.messages.stream(...)\`).
                        - If you want to capture LLM events anonymously, **don't** pass a distinct ID to the request.

                        See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        `}
                    </Markdown>
                </Blockquote>

                <Markdown>
                    {dedent`
                        You can expect captured \`$ai_generation\` events to have the following properties:
                    `}
                </Markdown>

                {NotableGenerationProperties && <NotableGenerationProperties />}
            </Step>

            <Step
                checkpoint
                title="Verify traces and generations"
                subtitle="Confirm LLM events are being sent to PostHog"
                docsOnly
            >
                <Markdown>
                    Let's make sure LLM events are being captured and sent to PostHog. Under **LLM analytics**, you
                    should see rows of data appear in the **Traces** and **Generations** tabs.
                </Markdown>

                <br />
                <ProductScreenshot
                    imageLight="https://res.cloudinary.com/dmukukwp6/image/upload/SCR_20250807_syne_ecd0801880.png"
                    imageDark="https://res.cloudinary.com/dmukukwp6/image/upload/SCR_20250807_syjm_5baab36590.png"
                    alt="LLM generations in PostHog"
                    classes="rounded"
                    className="mt-10"
                    padding={false}
                />

                <OSButton
                    variant="secondary"
                    asLink
                    className="my-2"
                    size="sm"
                    to="https://app.posthog.com/llm-analytics/generations"
                    external
                >
                    Check for LLM events in PostHog
                </OSButton>
            </Step>
        </Steps>
    )
}
