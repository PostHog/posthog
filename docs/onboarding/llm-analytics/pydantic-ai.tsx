import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getPydanticAISteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The Pydantic AI integration uses
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
            title: 'Install Pydantic AI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install Pydantic AI with OpenAI support. PostHog instruments your LLM calls by wrapping the
                        OpenAI client that Pydantic AI uses.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install 'pydantic-ai[openai]'
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and Pydantic AI',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a PostHog `AsyncOpenAI`
                        wrapper, pass it to an `OpenAIProvider`, and use that with Pydantic AI's `OpenAIChatModel`.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from pydantic_ai import Agent
                            from pydantic_ai.models.openai import OpenAIChatModel
                            from pydantic_ai.providers.openai import OpenAIProvider
                            from posthog.ai.openai import AsyncOpenAI
                            from posthog import Posthog

                            posthog = Posthog(
                                "<ph_project_api_key>",
                                host="<ph_client_api_host>"
                            )

                            openai_client = AsyncOpenAI(
                                api_key="your_openai_api_key",
                                posthog_client=posthog
                            )

                            provider = OpenAIProvider(openai_client=openai_client)

                            model = OpenAIChatModel(
                                "gpt-4o-mini",
                                provider=provider
                            )
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            PostHog's `AsyncOpenAI` wrapper is a proper subclass of `openai.AsyncOpenAI`, so it works
                            directly as the client for Pydantic AI's `OpenAIProvider`. PostHog captures
                            `$ai_generation` events automatically without proxying your calls.
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
                        Create a Pydantic AI agent with the model and run it. PostHog automatically captures an
                        `$ai_generation` event for each LLM call.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            agent = Agent(
                                model,
                                system_prompt="You are a helpful assistant.",
                            )

                            result = agent.run_sync(
                                "Tell me a fun fact about hedgehogs.",
                                # Pass PostHog metadata via the OpenAI client's extra params
                            )

                            print(result.output)
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

export const PydanticAIInstallation = createInstallation(getPydanticAISteps)
