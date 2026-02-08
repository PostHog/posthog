import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAutoGenSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The AutoGen integration uses
                        PostHog's OpenAI wrapper since AutoGen uses OpenAI under the hood.
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
            title: 'Install AutoGen',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install AutoGen with the OpenAI extension. PostHog instruments your LLM calls by wrapping the
                        OpenAI client that AutoGen uses internally.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install "autogen-agentchat" "autogen-ext[openai]"
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and AutoGen',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a PostHog OpenAI wrapper and
                        pass it to AutoGen's `OpenAIChatCompletionClient`.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import asyncio
                            from posthog.ai.openai import OpenAI
                            from posthog import Posthog
                            from autogen_agentchat.agents import AssistantAgent
                            from autogen_ext.models.openai import OpenAIChatCompletionClient

                            posthog = Posthog(
                                "<ph_project_api_key>",
                                host="<ph_client_api_host>"
                            )

                            openai_client = OpenAI(
                                api_key="your_openai_api_key",
                                posthog_client=posthog,
                            )

                            model_client = OpenAIChatCompletionClient(
                                model="gpt-4o",
                                openai_client=openai_client,
                            )
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            AutoGen's `OpenAIChatCompletionClient` accepts a custom OpenAI client via the
                            `openai_client` parameter. PostHog's `OpenAI` wrapper is a proper subclass of
                            `openai.OpenAI`, so it works directly. PostHog captures `$ai_generation` events
                            automatically without proxying your calls.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your agents',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use AutoGen as normal. PostHog automatically captures an `$ai_generation` event for each LLM
                        call made through the wrapped OpenAI client.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            agent = AssistantAgent("assistant", model_client=model_client)

                            async def main():
                                result = await agent.run(task="Say 'Hello World!'")
                                print(result)
                                await model_client.close()

                            asyncio.run(main())
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

export const AutoGenInstallation = createInstallation(getAutoGenSteps)
