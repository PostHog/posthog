import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLlamaIndexSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK. The LlamaIndex integration uses
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
            title: 'Install LlamaIndex',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install LlamaIndex with the OpenAI integration. PostHog instruments your LLM calls by wrapping
                        the OpenAI client that LlamaIndex uses.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install llama-index llama-index-llms-openai
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog and LlamaIndex',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a PostHog OpenAI wrapper and
                        pass it to LlamaIndex's `OpenAI` LLM class.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from llama_index.llms.openai import OpenAI as LlamaOpenAI
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

                            llm = LlamaOpenAI(
                                model="gpt-4o-mini",
                                api_key="your_openai_api_key",
                            )
                            llm._client = openai_client
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            PostHog's `OpenAI` wrapper is a proper subclass of `openai.OpenAI`, so it can replace the
                            internal client used by LlamaIndex's OpenAI LLM. PostHog captures `$ai_generation` events
                            automatically without proxying your calls.

                            **Note:** This approach accesses an internal attribute (`_client`) which may change in future
                            LlamaIndex versions. Check for updates if you encounter issues after upgrading LlamaIndex.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Query with LlamaIndex',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use LlamaIndex as normal. PostHog automatically captures an `$ai_generation` event for each LLM
                        call made through the wrapped client.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

                            # Load your documents
                            documents = SimpleDirectoryReader("data").load_data()

                            # Create an index
                            index = VectorStoreIndex.from_documents(documents, llm=llm)

                            # Query the index
                            query_engine = index.as_query_engine(llm=llm)
                            response = query_engine.query("What is this document about?")

                            print(response)
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

export const LlamaIndexInstallation = createInstallation(getLlamaIndexSteps)
