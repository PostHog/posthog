import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getSemanticKernelSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The Semantic Kernel integration uses
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
            title: 'Install Semantic Kernel',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install Semantic Kernel with OpenAI support. PostHog instruments your LLM calls by wrapping the
                        OpenAI client that Semantic Kernel uses under the hood.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install semantic-kernel
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and Semantic Kernel',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a PostHog `AsyncOpenAI` wrapper
                        and pass it to Semantic Kernel's `OpenAIChatCompletion` service.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from semantic_kernel import Kernel
                            from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
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

                            kernel = Kernel()
                            kernel.add_service(
                                OpenAIChatCompletion(
                                    ai_model_id="gpt-4o-mini",
                                    async_client=openai_client,
                                )
                            )
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            PostHog's `AsyncOpenAI` wrapper is a proper subclass of `openai.AsyncOpenAI`, so it works
                            directly as the `async_client` parameter in Semantic Kernel's `OpenAIChatCompletion`. PostHog
                            captures `$ai_generation` events automatically without proxying your calls.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your kernel function',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use Semantic Kernel as normal. PostHog automatically captures an `$ai_generation` event for each
                        LLM call made through the wrapped client.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import asyncio

                            async def main():
                                result = await kernel.invoke_prompt("Tell me a fun fact about hedgehogs.")
                                print(result)

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

export const SemanticKernelInstallation = createInstallation(getSemanticKernelSteps)
