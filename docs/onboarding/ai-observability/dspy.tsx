import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getDSPySteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The DSPy integration uses PostHog's
                        LiteLLM callback.
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
            title: 'Install DSPy and LiteLLM',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install DSPy and LiteLLM. DSPy uses LiteLLM natively for provider access, and PostHog integrates
                        with LiteLLM's callback system.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install dspy litellm
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
                            import dspy
                            import litellm

                            # Set PostHog environment variables
                            os.environ["POSTHOG_API_KEY"] = "<ph_project_token>"
                            os.environ["POSTHOG_API_URL"] = "<ph_client_api_host>"

                            # Enable PostHog callbacks in LiteLLM
                            litellm.success_callback = ["posthog"]
                            litellm.failure_callback = ["posthog"]

                            # Configure DSPy to use an LLM
                            lm = dspy.LM(
                                "openai/gpt-5-mini",
                                api_key="your_openai_api_key",
                                metadata={
                                    "user_id": "user_123",  # Maps to PostHog distinct_id
                                    "$ai_session_id": "conversation-abc",  # Groups calls into one session
                                },
                            )
                            dspy.configure(lm=lm)
                        `}
                    />

                    <Markdown>
                        Pass `user_id` and `$ai_session_id` in `metadata` to identify the caller and group every call
                        made through that LM into one PostHog session. Both forward straight through LiteLLM's callback
                        like any other metadata key.
                    </Markdown>

                    <Markdown>
                        {dedent`
                            \`user_id\` ties this call to a person, mapped to PostHog's \`distinct_id\`. This lets
                            you see everything one user asked for and know who hit an error or ran up cost.
                            \`$ai_session_id\` groups every call made through that LM into one conversation, so a
                            multi-turn exchange reads as a single thread instead of separate, unrelated calls.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            A trace covers one call, and a session covers the whole conversation: passing the same
                            session id across every call is what connects them. Together, they give you a complete
                            view: who made the request, which conversation it is part of, and every generation and
                            tool call inside it.
                        `}
                    </Markdown>

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            DSPy uses LiteLLM under the hood for LLM provider access. By configuring PostHog as a
                            LiteLLM callback, all LLM calls made through DSPy are automatically captured as
                            `$ai_generation` events.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run DSPy modules',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Use DSPy as normal. PostHog automatically captures an \`$ai_generation\` event for each
                            LLM call made through LiteLLM. LiteLLM's callback does not see a retrieval step or any
                            other work your own code does around it. Capture that as a span yourself, as the
                            example below does before calling \`predictor\`.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            LiteLLM has no \`posthog_trace_id\` parameter, so generate the trace id yourself and
                            pass it to \`dspy.LM()\` alongside \`$ai_session_id\`. Reuse that same trace id when you
                            capture the span, so it nests under the same trace as the generation that follows it.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog import Posthog
                            import time, uuid

                            posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                            session_id = "conversation-abc"  # same across every turn of the conversation
                            trace_id = str(uuid.uuid4())     # one per turn
                            user_id = "user_123"

                            lm = dspy.LM(
                                "openai/gpt-5-mini",
                                api_key="your_openai_api_key",
                                metadata={
                                    "user_id": user_id,
                                    "$ai_session_id": session_id,
                                    "$ai_trace_id": trace_id,
                                },
                            )
                            dspy.configure(lm=lm)

                            # retrieve() is your existing retrieval setup
                            start = time.time()
                            context = retrieve("hedgehog facts")

                            posthog.capture(
                                distinct_id=user_id,
                                event="$ai_span",
                                properties={
                                    "$ai_trace_id": trace_id,
                                    "$ai_session_id": session_id,
                                    "$ai_span_id": str(uuid.uuid4()),
                                    "$ai_span_name": "retrieve",
                                    "$ai_input_state": "hedgehog facts",
                                    "$ai_output_state": context,
                                    "$ai_latency": time.time() - start,
                                },
                            )

                            # Define a simple signature
                            class QA(dspy.Signature):
                                """Answer the question."""
                                question: str = dspy.InputField()
                                answer: str = dspy.OutputField()

                            predictor = dspy.Predict(QA)
                            question = f"Using this context, answer what a fun fact about hedgehogs is: {context}"
                            result = predictor(question=question)
                            print(result.answer)
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
        {
            title: 'Capture tool calls as spans',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            The recommended example above already captures a retrieval step as a span, ahead of
                            the generation that uses its output. Use the same pattern for a tool call or any other
                            work you want timed inside the trace.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            The span must carry the same \`$ai_trace_id\` as the generation it belongs to, or it
                            will not nest under the same trace. Nothing measures duration for you: time your own
                            code and pass the result as \`$ai_latency\`. Set \`$ai_span_type\` to describe the kind
                            of work, for example \`tool\`, \`chain\`, \`retriever\`, or \`agent\`.
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

export const DSPyInstallation = createInstallation(getDSPySteps)
