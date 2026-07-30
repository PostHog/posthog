import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getCrewAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. CrewAI uses LiteLLM under the hood,
                        and PostHog integrates with LiteLLM's callback system.
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
            title: 'Install CrewAI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install CrewAI. PostHog instruments your LLM calls through LiteLLM's callback system that CrewAI
                        uses natively.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install crewai litellm
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog with LiteLLM',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Set your PostHog project token and host as environment variables, then configure LiteLLM to use
                        PostHog as a callback handler. You can find your project token in [your project
                        settings](https://app.posthog.com/settings/project).
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import os
                            import litellm
                            from crewai import Agent, Task, Crew, LLM

                            # Set PostHog environment variables
                            os.environ["POSTHOG_API_KEY"] = "<ph_project_token>"
                            os.environ["POSTHOG_API_URL"] = "<ph_client_api_host>"

                            # Enable PostHog callbacks in LiteLLM
                            litellm.success_callback = ["posthog"]
                            litellm.failure_callback = ["posthog"]
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            CrewAI can route LLM calls either through its own provider clients or through LiteLLM.
                            PostHog hooks into LiteLLM's callback system, so you need `is_litellm=True` on the `LLM` you
                            pass to your agents. With it, every call is captured as an `$ai_generation` event without
                            proxying your calls.
                        </Markdown>
                    </CalloutBox>

                    <CalloutBox type="caution" icon="IconWarning" title="PostHog SDK version">
                        <Markdown>
                            {dedent`
                                CrewAI installs \`chromadb\`, which pins \`posthog<6.0.0\`. The AI observability
                                wrappers and the LangChain handler work on 5.x, so CrewAI tracing is unaffected.
                                But \`posthog.ai.otel\` was added in 7.12.0, so the OpenTelemetry integration
                                cannot be installed alongside CrewAI unless you override chromadb's pin.
                            `}
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your crew',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Run your CrewAI agents as normal. PostHog automatically captures generation events for each LLM
                        call.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            # is_litellm=True routes calls through LiteLLM so the PostHog
                            # callback fires. Without it, CrewAI uses its own provider client
                            # and no events are captured.
                            llm = LLM(model="gpt-4o-mini", is_litellm=True)

                            researcher = Agent(
                                role="Researcher",
                                goal="Find interesting facts about hedgehogs",
                                backstory="You are an expert wildlife researcher.",
                                llm=llm,
                            )

                            task = Task(
                                description="Research three fun facts about hedgehogs.",
                                expected_output="A list of three fun facts.",
                                agent=researcher,
                            )

                            crew = Crew(
                                agents=[researcher],
                                tasks=[task],
                            )

                            result = crew.kickoff()
                            print(result)
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

export const CrewAIInstallation = createInstallation(getCrewAISteps)
