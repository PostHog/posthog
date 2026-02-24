import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getMastraSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
            title: 'Install Mastra',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install Mastra and a model provider SDK. Mastra uses the Vercel AI SDK under the hood, so you can use any Vercel AI-compatible model provider.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install @mastra/core @ai-sdk/openai
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
            title: 'Initialize PostHog and wrap your model',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project settings](https://app.posthog.com/settings/project), then use `withTracing` from `@posthog/ai` to wrap the model you pass to your Mastra agent.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            import { Agent } from "@mastra/core/agent";
                            import { PostHog } from "posthog-node";
                            import { withTracing } from "@posthog/ai";
                            import { createOpenAI } from "@ai-sdk/openai";

                            const phClient = new PostHog(
                              '<ph_project_api_key>',
                              { host: '<ph_client_api_host>' }
                            );

                            const openaiClient = createOpenAI({
                              apiKey: 'your_openai_api_key',
                              compatibility: 'strict'
                            });

                            const agent = new Agent({
                              name: "my-agent",
                              instructions: "You are a helpful assistant.",
                              model: withTracing(openaiClient("gpt-4o"), phClient, {
                                posthogDistinctId: "user_123", // optional
                                posthogTraceId: "trace_123", // optional
                                posthogProperties: { conversationId: "abc123" }, // optional
                                posthogPrivacyMode: false, // optional
                                posthogGroups: { company: "companyIdInYourDb" }, // optional
                              }),
                            });
                        `}
                    />

                    <Markdown>
                        You can enrich LLM events with additional data by passing parameters such as the trace ID, distinct ID, custom properties, groups, and privacy mode options.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Use your Mastra agent',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Now, when your Mastra agent makes LLM calls, PostHog automatically captures an `$ai_generation` event for each one.
                    </Markdown>

                    <CodeBlock
                        language="typescript"
                        code={dedent`
                            const result = await agent.generate("What is the capital of France?");

                            console.log(result.text);

                            phClient.shutdown();
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

export const MastraInstallation = createInstallation(getMastraSteps)
