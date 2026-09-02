import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLangGraphSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install dependencies',
            badge: 'required',
            content: (
                <>
                    <CalloutBox type="info" icon="IconInfo" title="Full working examples">
                        <Markdown>
                            See the complete
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-langgraph) and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-langgraph)
                            examples on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the PostHog SDK and LangGraph with OpenAI.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog langgraph langchain-core langchain-openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install posthog-node @posthog/ai @langchain/langgraph @langchain/openai @langchain/core zod
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                        Create a PostHog client once, then build a callback handler for each request or
                        conversation. \`distinct_id\` ties each call to a user, and \`$ai_session_id\` groups calls in one conversation.
                    `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                from posthog import Posthog
                                from posthog.ai.langchain import CallbackHandler

                                posthog = Posthog("<ph_project_token>", host="<ph_client_api_host>")

                                def create_handler(user_id: str, session_id: str) -> CallbackHandler:
                                    return CallbackHandler(
                                        client=posthog,
                                        distinct_id=user_id,
                                        properties={"$ai_session_id": session_id},
                                    )
                            `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                import { PostHog } from 'posthog-node'
                                import { LangChainCallbackHandler } from '@posthog/ai/langchain'

                                const posthog = new PostHog('<ph_project_token>', { host: '<ph_client_api_host>' })

                                function createHandler(userId: string, sessionId: string): LangChainCallbackHandler {
                                  return new LangChainCallbackHandler({
                                    client: posthog,
                                    distinctId: userId,
                                    properties: { $ai_session_id: sessionId },
                                  })
                                }
                            `,
                            },
                        ]}
                    />

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit `distinct_id`/`distinctId`
                            when constructing the handler. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Run your graph',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Attach the handler through \`config\` when you invoke the graph, inside the function
                            that handles a turn. Because \`create_react_agent\` runs the turn as a single root
                            run, PostHog nests each tool call as an \`$ai_span\` under the trace automatically,
                            with real latency.
                        `}
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

                                    def ask(user_input: str, user_id: str, conversation_id: str) -> str:
                                        handler = create_handler(user_id=user_id, session_id=conversation_id)
                                        result = agent.invoke(
                                            {"messages": [{"role": "user", "content": user_input}]},
                                            config={"callbacks": [handler]},
                                        )
                                        return result["messages"][-1].content

                                    print(ask("What's the weather in Paris?", "user_123", "conversation-abc"))
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { createReactAgent } from '@langchain/langgraph/prebuilt'
                                    import { ChatOpenAI } from '@langchain/openai'
                                    import { tool } from '@langchain/core/tools'
                                    import { z } from 'zod'

                                    const getWeather = tool(
                                      (input) => \`It's always sunny in \${input.city}!\`,
                                      {
                                        name: 'get_weather',
                                        description: 'Get the weather for a given city',
                                        schema: z.object({
                                          city: z.string().describe('The city to get the weather for'),
                                        }),
                                      }
                                    )

                                    const model = new ChatOpenAI({ apiKey: 'your_openai_api_key' })
                                    const agent = createReactAgent({ model, tools: [getWeather] })

                                    async function ask(userInput: string, userId: string, conversationId: string): Promise<string> {
                                      const handler = createHandler(userId, conversationId)
                                      const result = await agent.invoke(
                                        { messages: [{ role: 'user', content: userInput }] },
                                        { callbacks: [handler] }
                                      )
                                      return result.messages[result.messages.length - 1].content
                                    }

                                    console.log(await ask("What's the weather in Paris?", 'user_123', 'conversation-abc'))
                                `,
                            },
                        ]}
                    />

                    <Markdown>
                        PostHog automatically captures an `$ai_generation` event along with these properties:
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}

                    <Markdown>
                        {dedent`
                            The handler also builds a trace hierarchy automatically based on how you structure
                            your graph. Pass the same \`$ai_session_id\` to every handler you construct for a
                            conversation, to group its calls into one session. Pass \`trace_id\`/\`traceId\`
                            too, to control the top-level trace ID instead of letting PostHog generate one.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const LangGraphInstallation = createInstallation(getLangGraphSteps)
