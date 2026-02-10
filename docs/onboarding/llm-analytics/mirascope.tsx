import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getMirascopeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The Mirascope integration uses
                        PostHog's OpenAI wrapper since Mirascope supports passing a custom OpenAI client.
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
            title: 'Install Mirascope',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install Mirascope with OpenAI support. PostHog instruments your LLM calls by wrapping the
                        OpenAI client that Mirascope uses under the hood.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install mirascope openai
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and Mirascope',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a PostHog OpenAI wrapper and
                        pass it to Mirascope's `@call` decorator via the `client` parameter.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from mirascope.llm import call
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
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            Mirascope's `@call` decorator accepts a `client` parameter for passing a custom OpenAI client.
                            PostHog's `OpenAI` wrapper is a proper subclass of `openai.OpenAI`, so it works directly.
                            PostHog captures `$ai_generation` events automatically without proxying your calls.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Make your first call',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use Mirascope as normal, passing the wrapped client to the call decorator. PostHog automatically
                        captures an `$ai_generation` event for each LLM call.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            @call(model="openai/gpt-4o-mini", client=openai_client)
                            def recommend_book(genre: str):
                                return f"Recommend a {genre} book."

                            response = recommend_book(
                                "fantasy",
                                posthog_distinct_id="user_123",
                                posthog_trace_id="trace_123",
                                posthog_properties={"conversation_id": "abc123"},
                            )

                            print(response.content)
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

export const MirascopeInstallation = createInstallation(getMirascopeSteps)
