import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

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
                        Set your PostHog project API key and host as environment variables, then configure LiteLLM to
                        use PostHog as a callback handler. You can find your API key in [your project
                        settings](https://app.posthog.com/settings/project).
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import os
                            import litellm
                            from crewai import Agent, Task, Crew

                            # Set PostHog environment variables
                            os.environ["POSTHOG_API_KEY"] = "<ph_project_api_key>"
                            os.environ["POSTHOG_API_URL"] = "<ph_client_api_host>"

                            # Enable PostHog callbacks in LiteLLM
                            litellm.success_callback = ["posthog"]
                            litellm.failure_callback = ["posthog"]
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            CrewAI uses LiteLLM under the hood for LLM provider access. By configuring PostHog as a
                            LiteLLM callback, all LLM calls made through CrewAI are automatically captured as
                            `$ai_generation` events without proxying your calls.
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
                            researcher = Agent(
                                role="Researcher",
                                goal="Find interesting facts about hedgehogs",
                                backstory="You are an expert wildlife researcher.",
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
