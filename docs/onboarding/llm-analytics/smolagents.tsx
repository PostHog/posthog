import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getSmolagentsSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The smolagents integration uses
                        PostHog's OpenAI wrapper.
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
            title: 'Install smolagents and OpenAI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install smolagents and the OpenAI SDK. PostHog instruments your LLM calls by wrapping the OpenAI
                        client, which you can pass to smolagents' `OpenAIServerModel`.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install smolagents openai
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and smolagents',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a PostHog OpenAI wrapper and
                        pass it to smolagents' `OpenAIServerModel`.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from smolagents import CodeAgent, OpenAIServerModel
                            from posthog.ai.openai import OpenAI
                            from posthog import Posthog

                            posthog = Posthog(
                                "<ph_project_api_key>",
                                host="<ph_client_api_host>"
                            )

                            openai_client = OpenAI(
                                api_key="your_openai_api_key",
                                posthog_client=posthog
                            )

                            model = OpenAIServerModel(
                                model_id="gpt-4o-mini",
                                client=openai_client,
                            )
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            PostHog's `OpenAI` wrapper is a drop-in replacement for `openai.OpenAI`. By passing it as
                            the `client` to `OpenAIServerModel`, all LLM calls made by smolagents are automatically
                            captured as `$ai_generation` events.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your agent',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use smolagents as normal. PostHog automatically captures an `$ai_generation` event for each LLM
                        call made through the wrapped OpenAI client.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            agent = CodeAgent(
                                tools=[],
                                model=model,
                            )

                            result = agent.run(
                                "What is a fun fact about hedgehogs?"
                            )

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

export const SmolagentsInstallation = createInstallation(getSmolagentsSteps)
