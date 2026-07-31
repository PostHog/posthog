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
                            llm = LLM(
                                model="gpt-4o-mini",
                                is_litellm=True,
                                metadata={
                                    "user_id": "user_123",  # Maps to PostHog distinct_id
                                    "$ai_session_id": "conversation-abc",  # Groups calls into one session
                                },
                            )

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
                        Pass `user_id` and `$ai_session_id` in the `metadata` on `LLM()` to identify the caller and
                        group every call made through that LLM into one PostHog session. Both forward straight through
                        LiteLLM's callback like any other metadata key.
                    </Markdown>

                    <Markdown>
                        {dedent`
                            \`user_id\` ties this call to a person, mapped to PostHog's \`distinct_id\`, so you can
                            see everything one user asked for and know who hit an error or ran up cost.
                            \`$ai_session_id\` groups every call made through that \`LLM\` into one conversation, so
                            a multi-turn exchange reads as a single thread instead of separate, unrelated calls. A
                            trace covers one call, and a session covers the whole conversation: passing the same
                            session id across every call is what connects them. Together, they give you a complete
                            view: who made the request, which conversation it's part of, and every generation and
                            tool call inside it.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            You can expect captured \`$ai_generation\` events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
        {
            title: 'Capture tool calls as spans',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            LiteLLM's PostHog callback captures the \`$ai_generation\` event for each LLM call your
                            crew makes, but it never sees the tools your agents call. CrewAI also doesn't hand you a
                            response object to inspect for tool calls the way a raw LLM client would, so capture a
                            tool's own execution as a span from inside the tool itself instead.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            LiteLLM has no \`posthog_trace_id\` parameter, so generate the trace id yourself and
                            pass it to \`LLM()\` alongside \`$ai_session_id\`. Reuse that same trace id inside the
                            tool, so its span nests under the same trace as the generations \`kickoff()\` produces.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog import Posthog
                            from crewai.tools import tool
                            import time, uuid

                            posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                            session_id = "conversation-abc"  # same across every turn of the conversation
                            trace_id = str(uuid.uuid4())     # one per crew run
                            user_id = "user_123"

                            @tool
                            def get_weather(city: str) -> str:
                                """Look up the weather for a given city."""
                                start = time.time()
                                result = f"It's always sunny in {city}!"

                                posthog.capture(
                                    distinct_id=user_id,
                                    event="$ai_span",
                                    properties={
                                        "$ai_trace_id": trace_id,
                                        "$ai_session_id": session_id,
                                        "$ai_span_id": str(uuid.uuid4()),
                                        "$ai_span_name": "get_weather",
                                        "$ai_input_state": {"city": city},
                                        "$ai_output_state": result,
                                        "$ai_latency": time.time() - start,
                                    },
                                )
                                return result

                            llm = LLM(
                                model="gpt-4o-mini",
                                is_litellm=True,
                                metadata={
                                    "user_id": user_id,
                                    "$ai_session_id": session_id,
                                    "$ai_trace_id": trace_id,
                                },
                            )

                            researcher = Agent(
                                role="Researcher",
                                goal="Find the weather in a city",
                                backstory="You are an expert wildlife researcher.",
                                llm=llm,
                                tools=[get_weather],
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
                            The span must carry the same \`$ai_trace_id\` as the generation it belongs to, or it
                            won't nest under the same trace. Nothing measures duration for you: time your own code
                            and pass the result as \`$ai_latency\`. Set \`$ai_span_type\` to describe the kind of
                            work, for example \`tool\`, \`chain\`, \`retriever\`, or \`agent\`.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            See [spans](https://posthog.com/docs/ai-observability/spans) for the full list of span
                            properties.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const CrewAIInstallation = createInstallation(getCrewAISteps)
