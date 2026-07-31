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
                        Attach the handler through `config` when you invoke your chain. PostHog captures an
                        `$ai_generation` event for each LLM call and an `$ai_span` event for each tool call.
                    </Markdown>

                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                    from langchain_openai import ChatOpenAI
                                    from langchain_core.tools import tool
                                    from langchain_core.runnables import RunnableLambda

                                    @tool
                                    def get_weather(city: str) -> str:
                                        """Get the weather for a given city."""
                                        return f"It's always sunny in {city}!"

                                    model = ChatOpenAI(openai_api_key="your_openai_api_key").bind_tools([get_weather])

                                    def run_turn(user_input: str) -> str:
                                        # Wrapping the whole turn in one RunnableLambda gives the tool call a
                                        # parent run. Without a parent, the handler logs it as its own
                                        # $ai_trace instead of an $ai_span.
                                        response = model.invoke(user_input)

                                        for tool_call in response.tool_calls:
                                            print(get_weather.invoke(tool_call))

                                        return response.content

                                    agent_turn = RunnableLambda(run_turn)

                                    handler = create_handler(user_id="user_123", session_id="conversation-abc")
                                    result = agent_turn.invoke(
                                        "What's the weather in Paris?",
                                        config={"callbacks": [handler]},
                                    )

                                    print(result)
                                `,
                            },
                            {
                                language: 'typescript',
                                file: 'Node',
                                code: dedent`
                                    import { ChatOpenAI } from '@langchain/openai'
                                    import { tool } from '@langchain/core/tools'
                                    import { RunnableLambda } from '@langchain/core/runnables'
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

                                    const model = new ChatOpenAI({ apiKey: 'your_openai_api_key' }).bindTools([getWeather])

                                    const agentTurn = RunnableLambda.from(async (userInput: string, config) => {
                                      // Wrapping the whole turn in one RunnableLambda gives the tool call a
                                      // parent run, and passing config into every nested call keeps it there —
                                      // LangChain.js doesn't propagate callbacks implicitly the way Python does.
                                      const response = await model.invoke(userInput, config)

                                      for (const toolCall of response.tool_calls ?? []) {
                                        console.log(await getWeather.invoke(toolCall, config))
                                      }

                                      return response.content
                                    })

                                    const handler = createHandler('user_123', 'conversation-abc')
                                    const result = await agentTurn.invoke("What's the weather in Paris?", {
                                      callbacks: [handler],
                                    })

                                    console.log(result)
                                `,
                            },
                        ]}
                    />

                    <CalloutBox type="caution" icon="IconWarning" title="Config propagation and tool spans">
                        <Markdown>
                            {dedent`
                                **In Node, pass \`config\` into every nested call.** Python threads the active
                                callbacks through contextvars automatically, so nested \`.invoke()\` calls pick them up
                                on their own. LangChain.js doesn't — skip \`config\` on a nested call and that call runs
                                with no callbacks at all. Nothing errors, so you're left with a single root trace and
                                no generations or spans, silently.

                                **Tool calls need a parent run.** The handler decides whether a call is a trace or a
                                span based on whether it has a parent run. A tool invoked with no enclosing chain
                                becomes its own root, producing a second, disconnected \`$ai_trace\` instead of an
                                \`$ai_span\`.
                                Wrapping the turn in one \`RunnableLambda\`, as above, fixes it in both Python and
                                Node. This only comes up when you hand-roll a loop like this one — a prebuilt agent,
                                like LangGraph's
                                [\`create_react_agent\`](https://posthog.com/docs/ai-observability/installation/langgraph),
                                already runs as a single root.
                            `}
                        </Markdown>
                    </CalloutBox>

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
                            The handler also builds a trace hierarchy automatically based on how your chain is
                            nested. Pass the same \`$ai_session_id\` to every handler you construct for a conversation
                            to group its calls into one session, and \`trace_id\`/\`traceId\` to control the top-level
                            trace ID instead of letting PostHog generate one.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const LangChainInstallation = createInstallation(getLangChainSteps)
