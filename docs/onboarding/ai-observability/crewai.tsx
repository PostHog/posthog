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
                            pass to your agents. With it, PostHog captures every call as an `$ai_generation` event,
                            without proxying your calls.
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
                        {dedent`
                            Run your CrewAI agents as normal. PostHog automatically captures an \`$ai_generation\`
                            event for each LLM call. LiteLLM's callback does not see the tools your agents call.
                            Capture a tool's own execution as a span from inside the tool itself instead, as
                            \`my_tool\` does below.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog import Posthog
                            from crewai.tools import tool
                            import time, uuid

                            posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                            trace_id = str(uuid.uuid4())

                            @tool
                            def my_tool(query: str) -> str:
                                """Describe what your tool does."""
                                start = time.time()
                                result = run_tool(query)

                                posthog.capture(
                                    distinct_id="user_123",
                                    event="$ai_span",
                                    properties={
                                        "$ai_trace_id": trace_id,
                                        "$ai_session_id": "conversation-abc",
                                        "$ai_span_id": str(uuid.uuid4()),
                                        "$ai_span_name": "my_tool",
                                        "$ai_input_state": {"query": query},
                                        "$ai_output_state": result,
                                        "$ai_latency": time.time() - start,
                                    },
                                )
                                return result

                            # is_litellm=True routes calls through LiteLLM so the PostHog
                            # callback fires. Without it, CrewAI uses its own provider client
                            # and no events are captured.
                            llm = LLM(
                                model="gpt-4o-mini",
                                is_litellm=True,
                                metadata={
                                    "user_id": "user_123",
                                    "$ai_session_id": "conversation-abc",
                                    "$ai_trace_id": trace_id,
                                },
                            )

                            researcher = Agent(
                                role="Researcher",
                                goal="Find the weather in a city",
                                backstory="You are an expert wildlife researcher.",
                                llm=llm,
                                tools=[my_tool],
                            )

                            task = Task(
                                description="Find the weather in Paris.",
                                expected_output="The weather in Paris.",
                                agent=researcher,
                            )

                            crew = Crew(agents=[researcher], tasks=[task])
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
