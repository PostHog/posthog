import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const OpenAIAgentsInstallation = (): JSX.Element => {
    const {
        Steps,
        Step,
        CodeBlock,
        ProductScreenshot,
        OSButton,
        Markdown,
        Blockquote,
        dedent,
        snippets,
    } = useMDXComponents()

    const NotableGenerationProperties = snippets?.NotableGenerationProperties
    return (
        <Steps>
            <Step title="Install the PostHog SDK" badge="required">
                <Markdown>
                    Install the PostHog Python SDK with the OpenAI Agents SDK.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Terminal',
                            code: dedent`
                                pip install posthog openai-agents
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Initialize PostHog tracing" badge="required">
                <Markdown>
                    Import and call the `instrument()` helper to register PostHog tracing with the OpenAI Agents SDK. This automatically captures all agent traces, spans, and LLM generations.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                from posthog import Posthog
                                from posthog.ai.openai_agents import instrument

                                posthog = Posthog(
                                    "<ph_project_api_key>",
                                    host="<ph_client_api_host>"
                                )

                                # Register PostHog tracing with OpenAI Agents SDK
                                instrument(
                                    client=posthog,
                                    distinct_id="user_123",  # optional
                                    privacy_mode=False,  # optional - redact inputs/outputs
                                    groups={"company": "company_id"},  # optional
                                    properties={"environment": "production"},  # optional
                                )
                            `,
                        },
                    ]}
                />

                <Blockquote>
                    <Markdown>
                        **Note:** If you want to capture LLM events anonymously, **don't** pass a distinct ID to `instrument()`. See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                    </Markdown>
                </Blockquote>
            </Step>

            <Step title="Run your agents" badge="required">
                <Markdown>
                    Run your OpenAI agents as normal. PostHog automatically captures traces for agent execution, tool calls, handoffs, and LLM generations.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                from agents import Agent, Runner

                                agent = Agent(
                                    name="Assistant",
                                    instructions="You are a helpful assistant."
                                )

                                result = Runner.run_sync(agent, "Tell me a joke about programming")
                                print(result.final_output)
                            `,
                        },
                    ]}
                />

                <Markdown>
                    PostHog automatically captures `$ai_generation` events for LLM calls and `$ai_span` events for agent execution, tool calls, and handoffs.
                </Markdown>

                {NotableGenerationProperties && <NotableGenerationProperties />}
            </Step>

            <Step title="Multi-agent and tool usage" badge="optional">
                <Markdown>
                    PostHog captures the full trace hierarchy for complex agent workflows including handoffs and tool calls.
                </Markdown>

                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                from agents import Agent, Runner, function_tool

                                @function_tool
                                def get_weather(city: str) -> str:
                                    """Get the weather for a city."""
                                    return f"The weather in {city} is sunny, 72F"

                                weather_agent = Agent(
                                    name="WeatherAgent",
                                    instructions="You help with weather queries.",
                                    tools=[get_weather]
                                )

                                triage_agent = Agent(
                                    name="TriageAgent",
                                    instructions="Route weather questions to the weather agent.",
                                    handoffs=[weather_agent]
                                )

                                result = Runner.run_sync(triage_agent, "What's the weather in San Francisco?")
                            `,
                        },
                    ]}
                />

                <Markdown>
                    This captures:
                    - Agent spans for `TriageAgent` and `WeatherAgent`
                    - Handoff spans showing the routing between agents
                    - Tool spans for `get_weather` function calls
                    - Generation spans for all LLM calls
                </Markdown>
            </Step>

            <Step checkpoint title="Verify traces and generations" subtitle="Confirm LLM events are being sent to PostHog" docsOnly>
                <Markdown>
                    Under **LLM analytics**, you should see rows of data appear in the **Traces** and **Generations** tabs.
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

                <OSButton variant="secondary" asLink className="my-2" size="sm" to="https://app.posthog.com/llm-analytics/generations" external>
                    Check for LLM events in PostHog
                </OSButton>
            </Step>
        </Steps>
    )
}
