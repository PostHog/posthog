import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

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
                        Set your PostHog project API key and host as environment variables, then configure LiteLLM to
                        use PostHog as a callback handler. You can find your API key in [your project
                        settings](https://app.posthog.com/settings/project).
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import os
                            import dspy
                            import litellm

                            # Set PostHog environment variables
                            os.environ["POSTHOG_API_KEY"] = "<ph_project_api_key>"
                            os.environ["POSTHOG_API_URL"] = "<ph_client_api_host>"

                            # Enable PostHog callbacks in LiteLLM
                            litellm.success_callback = ["posthog"]
                            litellm.failure_callback = ["posthog"]

                            # Configure DSPy to use an LLM
                            lm = dspy.LM("openai/gpt-4o-mini", api_key="your_openai_api_key")
                            dspy.configure(lm=lm)
                        `}
                    />

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
                        Use DSPy as normal. PostHog automatically captures an `$ai_generation` event for each LLM call
                        made through LiteLLM.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            # Define a simple signature
                            class QA(dspy.Signature):
                                """Answer the question."""
                                question: str = dspy.InputField()
                                answer: str = dspy.OutputField()

                            # Create and run a module
                            predictor = dspy.Predict(QA)
                            result = predictor(
                                question="What is a fun fact about hedgehogs?"
                            )

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
    ]
}

export const DSPyInstallation = createInstallation(getDSPySteps)
