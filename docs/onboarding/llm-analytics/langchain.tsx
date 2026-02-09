import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getLangChainSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK for your language. LLM analytics works best with our Python and Node SDKs.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @posthog/ai posthog-node
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Install LangChain and OpenAI SDKs',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install LangChain. The PostHog SDK instruments your LLM calls by wrapping LangChain. The PostHog SDK
                        **does not** proxy your calls.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install langchain openai langchain-openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install langchain @langchain/core @posthog/ai
                                `,
                            },
                        ]}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="Proxy note">
                        <Markdown>
                            These SDKs **do not** proxy your calls. They only fire off an async call to PostHog in the background to send the data.

                            You can also use LLM analytics with other SDKs or our API, but you will need to capture the data in the right format. See the schema in the [manual capture section](https://posthog.com/docs/llm-analytics/installation/manual-capture) for more details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Initialize PostHog and LangChain',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project settings](https://app.posthog.com/settings/project), then pass it to the LangChain `CallbackHandler` wrapper.

                        Optionally, you can provide a user distinct ID, trace ID, PostHog properties, [groups](https://posthog.com/docs/product-analytics/group-analytics), and privacy mode.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog.ai.langchain import CallbackHandler
                                    from langchain_openai import ChatOpenAI
                                    from langchain_core.prompts import ChatPromptTemplate
                                    from posthog import Posthog

                                    posthog = Posthog(
                                        "<ph_project_api_key>",
                                        host="<ph_client_api_host>"
                                    )

                                    callback_handler = CallbackHandler(
                                        client=posthog, # This is an optional parameter. If it is not provided, a default client will be used.
                                        distinct_id="user_123", # optional
                                        trace_id="trace_456", # optional
                                        properties={"conversation_id": "abc123"} # optional
                                        groups={"company": "company_id_in_your_db"} # optional
                                        privacy_mode=False # optional
                                    )
                                `,
                            },
                            {
                                language: 'ts',
                                file: 'Node',
                                code: dedent`
                                    import { PostHog } from 'posthog-node';
                                    import { LangChainCallbackHandler } from '@posthog/ai';
                                    import { ChatOpenAI } from '@langchain/openai';
                                    import { ChatPromptTemplate } from '@langchain/core/prompts';

                                    const phClient = new PostHog(
                                      '<ph_project_api_key>',
                                      { host: '<ph_client_api_host>' }
                                    );

                                    const callbackHandler = new LangChainCallbackHandler({
                                      client: phClient,
                                      distinctId: 'user_123', // optional
                                      traceId: 'trace_456', // optional
                                      properties: { conversationId: 'abc123' }, // optional
                                      groups: { company: 'company_id_in_your_db' }, // optional
                                      privacyMode: false, // optional
                                      debug: false // optional - when true, logs all events to console
                                    });
                                `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, **don't** pass a distinct ID to the `CallbackHandler`. See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Call LangChain',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        When you invoke your chain, pass the `callback_handler` in the `config` as part of your `callbacks`:
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    prompt = ChatPromptTemplate.from_messages([
                                        ("system", "You are a helpful assistant."),
                                        ("user", "{input}")
                                    ])

                                    model = ChatOpenAI(openai_api_key="your_openai_api_key")
                                    chain = prompt | model

                                    # Execute the chain with the callback handler
                                    response = chain.invoke(
                                        {"input": "Tell me a joke about programming"},
                                        config={"callbacks": [callback_handler]}
                                    )

                                    print(response.content)
                                `,
                            },
                            {
                                language: 'ts',
                                file: 'Node',
                                code: dedent`
                                    const prompt = ChatPromptTemplate.fromMessages([
                                      ["system", "You are a helpful assistant."],
                                      ["user", "{input}"]
                                    ]);

                                    const model = new ChatOpenAI({
                                      apiKey: "your_openai_api_key"
                                    });

                                    const chain = prompt.pipe(model);

                                    // Execute the chain with the callback handler
                                    const response = await chain.invoke(
                                      { input: "Tell me a joke about programming" },
                                      { callbacks: [callbackHandler] }
                                    );

                                    console.log(response.content);
                                    phClient.shutdown();
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        PostHog automatically captures an `$ai_generation` event along with these properties:
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}

                    <Markdown>
                        It also automatically creates a trace hierarchy based on how LangChain components are nested.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const LangChainInstallation = createInstallation(getLangChainSteps)
