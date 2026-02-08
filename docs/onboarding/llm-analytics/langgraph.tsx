import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLangGraphSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Setting up analytics starts with installing the PostHog SDK for your language. LLM analytics
                        works best with our Python and Node SDKs.
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
            title: 'Install LangGraph',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install LangGraph and LangChain. PostHog instruments your LLM calls through LangChain-compatible
                        callback handlers that LangGraph supports.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install langgraph langchain-openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install @langchain/langgraph @langchain/openai @langchain/core
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog with your project API key and host from [your project
                        settings](https://app.posthog.com/settings/project), then create a LangChain `CallbackHandler`.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from posthog.ai.langchain import CallbackHandler
                                    from posthog import Posthog

                                    posthog = Posthog(
                                        "<ph_project_api_key>",
                                        host="<ph_client_api_host>"
                                    )

                                    callback_handler = CallbackHandler(
                                        client=posthog,
                                        distinct_id="user_123", # optional
                                        trace_id="trace_456", # optional
                                        properties={"conversation_id": "abc123"}, # optional
                                        groups={"company": "company_id_in_your_db"}, # optional
                                        privacy_mode=False # optional
                                    )
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { PostHog } from 'posthog-node';
                                    import { LangChainCallbackHandler } from '@posthog/ai';

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
                                    });
                                `,
                            },
                        ]}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="How this works">
                        <Markdown>
                            LangGraph is built on LangChain, so it supports LangChain-compatible callback handlers.
                            PostHog's `CallbackHandler` captures `$ai_generation` events and trace hierarchy
                            automatically without proxying your calls.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Run your graph',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Pass the `callback_handler` in the `config` when invoking your LangGraph graph. PostHog
                        automatically captures generation events for each LLM call.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from langgraph.prebuilt import create_react_agent
                                    from langchain_openai import ChatOpenAI
                                    from langchain_core.tools import tool

                                    @tool
                                    def get_weather(city: str) -> str:
                                        """Get the weather for a given city."""
                                        return f"It's always sunny in {city}!"

                                    model = ChatOpenAI(api_key="your_openai_api_key")
                                    agent = create_react_agent(model, tools=[get_weather])

                                    result = agent.invoke(
                                        {"messages": [{"role": "user", "content": "What's the weather in Paris?"}]},
                                        config={"callbacks": [callback_handler]}
                                    )

                                    print(result["messages"][-1].content)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { createReactAgent } from '@langchain/langgraph/prebuilt';
                                    import { ChatOpenAI } from '@langchain/openai';
                                    import { tool } from '@langchain/core/tools';
                                    import { z } from 'zod';

                                    const getWeather = tool(
                                      (input) => \`It's always sunny in \${input.city}!\`,
                                      {
                                        name: 'get_weather',
                                        description: 'Get the weather for a given city',
                                        schema: z.object({
                                          city: z.string().describe('The city to get the weather for'),
                                        }),
                                      }
                                    );

                                    const model = new ChatOpenAI({ apiKey: 'your_openai_api_key' });
                                    const agent = createReactAgent({ llm: model, tools: [getWeather] });

                                    const result = await agent.invoke(
                                      { messages: [{ role: 'user', content: "What's the weather in Paris?" }] },
                                      { callbacks: [callbackHandler] }
                                    );

                                    console.log(result.messages[result.messages.length - 1].content);
                                    phClient.shutdown();
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        {dedent`
                            PostHog automatically captures \`$ai_generation\` events and creates a trace hierarchy based on how LangGraph components are nested. You can expect captured events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
    ]
}

export const LangGraphInstallation = createInstallation(getLangGraphSteps)
