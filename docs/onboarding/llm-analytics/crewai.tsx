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
                        Setting up analytics starts with installing the PostHog SDK. The CrewAI integration uses
                        PostHog's LangChain callback handler.
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
                        Install CrewAI. PostHog instruments your LLM calls through LangChain-compatible callback
                        handlers that CrewAI supports.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install crewai
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and CrewAI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a LangChain `CallbackHandler`
                        and pass it to your CrewAI agents.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog.ai.langchain import CallbackHandler
                            from posthog import Posthog
                            from crewai import Agent, Task, Crew

                            posthog = Posthog(
                                "<ph_project_api_key>",
                                host="<ph_client_api_host>"
                            )

                            callback_handler = CallbackHandler(
                                client=posthog,
                                distinct_id="user_123", # optional
                                trace_id="trace_456", # optional
                                properties={"conversation_id": "abc123"}, # optional
                                groups={"company": "company_id_in_your_db"}, # optional
                                privacy_mode=False # optional
                            )
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            CrewAI supports LangChain-compatible callback handlers. PostHog's `CallbackHandler` captures
                            `$ai_generation` events and trace hierarchy automatically without proxying your calls.
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
                        Pass the `callback_handler` when creating your agents or crew via the `callbacks` parameter.
                        PostHog automatically captures generation events for each LLM call.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            researcher = Agent(
                                role="Researcher",
                                goal="Find interesting facts about hedgehogs",
                                backstory="You are an expert wildlife researcher.",
                                callbacks=[callback_handler],
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
                            PostHog automatically captures \`$ai_generation\` events and creates a trace hierarchy based on how CrewAI components are nested. You can expect captured events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
    ]
}

export const CrewAIInstallation = createInstallation(getCrewAISteps)
