import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getVercelAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @posthog/ai posthog-node
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Install the Vercel AI SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the Vercel AI SDK. The PostHog SDK instruments your LLM calls by wrapping the Vercel AI client.
                        The PostHog SDK **does not** proxy your calls.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install ai @ai-sdk/openai
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="Proxy note">
                        <Markdown>
                            These SDKs **do not** proxy your calls. They only fire off an async call to PostHog in the background to send the data.

                            You can also use LLM analytics with other SDKs or our API, but you will need to capture the data in the right format. See the schema in the [manual capture section](https://posthog.com/docs/llm-analytics/installation/manual-capture) for more details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Initialize PostHog and Vercel AI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project settings](https://app.posthog.com/settings/project), then pass the Vercel AI OpenAI client and the PostHog client to the `withTracing` wrapper.
                    </Markdown>

                    <CodeBlock
                        language="ts"
                        code={dedent`
                            import { PostHog } from "posthog-node";
                            import { withTracing } from "@posthog/ai"
                            import { generateText } from "ai"
                            import { createOpenAI } from "@ai-sdk/openai"

                            const phClient = new PostHog(
                              '<ph_project_api_key>',
                              { host: '<ph_client_api_host>' }
                            );

                            const openaiClient = createOpenAI({
                              apiKey: 'your_openai_api_key',
                              compatibility: 'strict'
                            });

                            const model = withTracing(openaiClient("gpt-4-turbo"), phClient, {
                              posthogDistinctId: "user_123", // optional
                              posthogTraceId: "trace_123", // optional
                              posthogProperties: { conversationId: "abc123", paid: true }, // optional
                              posthogPrivacyMode: false, // optional
                              posthogGroups: { company: "companyIdInYourDb" }, // optional
                            });

                            phClient.shutdown()
                        `}
                    />

                    <Markdown>
                        You can enrich LLM events with additional data by passing parameters such as the trace ID, distinct ID, custom properties, groups, and privacy mode options.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Call Vercel AI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Now, when you use the Vercel AI SDK to call LLMs, PostHog automatically captures an `$ai_generation` event.

                        This works for both `text` and `image` message types.
                    </Markdown>

                    <CodeBlock
                        language="ts"
                        code={dedent`
                            const { text } = await generateText({
                              model: model,
                              prompt: message
                            });

                            console.log(text)
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, **don't** pass a distinct ID to the request. See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
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
    ]
}

export const VercelAIInstallation = createInstallation(getVercelAISteps)
