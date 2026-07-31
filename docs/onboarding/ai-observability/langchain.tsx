import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLangChainSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
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
                            [Node.js](https://github.com/PostHog/posthog-js/tree/main/examples/example-ai-langchain) and
                            [Python](https://github.com/PostHog/posthog-python/tree/master/examples/example-ai-langchain)
                            examples on GitHub.
                        </Markdown>
                    </CalloutBox>

                    <Markdown>Install the PostHog SDK and LangChain with OpenAI.</Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Python',
                                code: dedent`
                                    pip install posthog langchain langchain-core langchain-openai
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Node',
                                code: dedent`
                                    npm install posthog-node @posthog/ai langchain @langchain/core @langchain/openai zod
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
                        Create a PostHog client once, then build a callback handler for each request or conversation.
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

                    <CalloutBox type="caution" icon="IconWarning" title="Build a new handler for every request">
                        <Markdown>
                            {dedent`
                                A \`CallbackHandler\` holds no state of its own, so \`distinct_id\` and \`$ai_session_id\`
                                are fixed when you construct it. Build one per request or conversation, as
                                \`create_handler\`/\`createHandler\` does above. Construct a single handler once at
                                module scope instead, and every user's conversation collapses into the same session.
                            `}
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Call LangChain',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Build your agent once, then invoke it inside the function that handles a turn. PostHog
                            captures an \`$ai_generation\` event for each LLM call and an \`$ai_span\` event for each
                            tool call, both nested under one trace, as long as the whole turn runs through a single
                            call to \`invoke\`.
                        `}
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from langchain_openai import ChatOpenAI
                                    from langchain_core.tools import tool
                                    from langchain.agents import create_agent

                                    @tool
                                    def get_weather(city: str) -> str:
                                        """Get the weather for a given city."""
                                        return f"It's always sunny in {city}!"

                                    model = ChatOpenAI(openai_api_key="your_openai_api_key")
                                    agent = create_agent(model, tools=[get_weather])

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
                                    import { ChatOpenAI } from '@langchain/openai'
                                    import { tool } from '@langchain/core/tools'
                                    import { createAgent } from 'langchain'
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
                                    const agent = createAgent({ llm: model, tools: [getWeather] })

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
                        {dedent`
                            \`agent\` is built once, outside \`ask\`, and reused across turns. The handler is built
                            fresh inside \`ask\` on every call, because it carries \`distinct_id\` and
                            \`$ai_session_id\`, and those need to change per conversation. \`create_agent\` and
                            \`createAgent\` build the tool-calling loop on LangGraph under the hood, the same engine
                            behind the
                            [LangGraph installation page](https://posthog.com/docs/ai-observability/installation/langgraph).
                            That's why the \`get_weather\` call above is captured automatically as an \`$ai_span\`
                            with its real execution duration, nested under the trace, without any extra code.
                        `}
                    </Markdown>

                    <Markdown>
                        {dedent`
                            \`distinct_id\` ties this call to a person, so you can see everything one user asked for
                            and know who hit an error or ran up cost. \`$ai_session_id\` groups every call in one
                            conversation, so a multi-turn exchange reads as a single thread instead of separate,
                            unrelated calls. A trace covers one turn, and a session covers the whole conversation:
                            passing the same session id to every handler you build for that conversation is what
                            connects them. Together, \`distinct_id\` and \`$ai_session_id\` give you a complete view:
                            which person, which conversation, which turn, and every LLM call and tool call inside it.
                        `}
                    </Markdown>

                    <Blockquote>
                        <Markdown>
                            **Note:** If you want to capture LLM events anonymously, omit `distinct_id`/`distinctId`
                            when constructing the handler. See our docs on [anonymous vs identified
                            events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                        </Markdown>
                    </Blockquote>

                    <Markdown>
                        PostHog automatically captures an `$ai_generation` event along with these properties:
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}

                    <Markdown>
                        {dedent`
                            The handler also builds a trace hierarchy automatically based on how your agent is
                            structured. Pass the same \`$ai_session_id\` to every handler you construct for a
                            conversation to group its calls into one session, and \`trace_id\`/\`traceId\` to control
                            the top-level trace ID instead of letting PostHog generate one.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const LangChainInstallation = createInstallation(getLangChainSteps)
