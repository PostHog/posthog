import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getOpenAIAgentsSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog Python SDK.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install posthog
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Install the OpenAI Agents SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the OpenAI Agents SDK. PostHog instruments your agent runs by registering a tracing
                        processor. The PostHog SDK **does not** proxy your calls.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install openai-agents
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="Proxy note">
                        <Markdown>
                            These SDKs **do not** proxy your calls. They only fire off an async call to PostHog in the
                            background to send the data. You can also use LLM analytics with other SDKs or our API, but
                            you will need to capture the data in the right format. See the schema in the [manual capture
                            section](https://posthog.com/docs/llm-analytics/installation/manual-capture) for more
                            details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Initialize PostHog tracing',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then call `instrument()` to register
                        PostHog tracing with the OpenAI Agents SDK. This automatically captures all agent traces,
                        spans, and LLM generations.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog import Posthog
                            from posthog.ai.openai_agents import instrument

                            posthog = Posthog(
                                "<ph_project_api_key>",
                                host="<ph_client_api_host>"
                            )

                            instrument(
                                client=posthog,
                                distinct_id="user_123", # optional
                                privacy_mode=False, # optional
                                groups={"company": "company_id_in_your_db"}, # optional
                                properties={"conversation_id": "abc123"}, # optional
                            )
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, **don't** pass a distinct ID to
                            `instrument()`. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Run your agents',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Run your OpenAI agents as normal. PostHog automatically captures `$ai_generation` events for
                        LLM calls and `$ai_span` events for agent execution, tool calls, and handoffs.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from agents import Agent, Runner

                            agent = Agent(
                                name="Assistant",
                                instructions="You are a helpful assistant.",
                            )

                            result = Runner.run_sync(agent, "Tell me a fun fact about hedgehogs")
                            print(result.final_output)
                        `}
                    />

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

export const OpenAIAgentsInstallation = createInstallation(getOpenAIAgentsSteps)
