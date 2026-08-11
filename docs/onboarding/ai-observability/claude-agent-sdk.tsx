import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getClaudeAgentSDKSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, CalloutBox, Markdown, Blockquote, dedent, snippets } = ctx

    const NotableGenerationProperties = snippets?.NotableGenerationProperties

    return [
        {
            title: 'Install the PostHog SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>Setting up analytics starts with installing the PostHog Python SDK.</Markdown>

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
            title: 'Install the Claude Agent SDK',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the Claude Agent SDK. PostHog instruments your agent queries by wrapping the `query()`
                        function. The PostHog SDK **does not** proxy your calls.
                    </Markdown>

                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pip install claude-agent-sdk
                        `}
                    />

                    <CalloutBox type="fyi" icon="IconInfo" title="Proxy note">
                        <Markdown>
                            These SDKs **do not** proxy your calls. They only fire off an async call to PostHog in the
                            background to send the data. You can also use AI observability with other SDKs or our API,
                            but you will need to capture the data in the right format. See the schema in the [manual
                            capture section](https://posthog.com/docs/ai-observability/installation/manual-capture) for
                            more details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Initialize PostHog and run a query',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Initialize PostHog with your project token and host from [your project
                            settings](https://app.posthog.com/settings/project). Then use the PostHog \`query()\`
                            wrapper as a drop-in replacement for \`claude_agent_sdk.query()\`. This automatically
                            captures \`$ai_generation\`, \`$ai_span\`, and \`$ai_trace\` events, including a span
                            for each tool the agent uses, such as \`Bash\` below.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import asyncio
                            from posthog import Posthog
                            from posthog.ai.claude_agent_sdk import query
                            from claude_agent_sdk import ClaudeAgentOptions

                            posthog = Posthog(
                                "<ph_project_token>",
                                host="<ph_client_api_host>"
                            )

                            async def main():
                                options = ClaudeAgentOptions(
                                    max_turns=5,
                                    allowed_tools=["Read", "Glob", "Grep"],
                                    cwd="/path/to/your/project",
                                )

                                async for message in query(
                                    prompt="Read the README and summarize this project",
                                    options=options,
                                    posthog_client=posthog,
                                    posthog_distinct_id="user_123", # optional
                                    posthog_trace_id="trace_123", # optional
                                    posthog_properties={"conversation_id": "abc123", "$ai_session_id": "conversation-abc"}, # optional
                                    posthog_groups={"company": "company_id_in_your_db"}, # optional
                                    posthog_privacy_mode=False, # optional
                                ):
                                    print(message)

                            asyncio.run(main())
                            posthog.shutdown()
                        `}
                    />

                    <Blockquote>
                        <Markdown>
                            {dedent`
                            **Notes:**
                            - The wrapper yields all original messages unchanged, fully transparent to your code.
                            - Pass \`$ai_session_id\` in \`posthog_properties\` to group every generation, span, and trace from a call into one PostHog session.
                            - If you want to capture LLM events anonymously, **do not** pass a distinct ID. See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
                            `}
                        </Markdown>
                    </Blockquote>

                    <Markdown>
                        {dedent`
                            You can expect captured \`$ai_generation\` events to have the following properties:
                        `}
                    </Markdown>

                    {NotableGenerationProperties && <NotableGenerationProperties />}
                </>
            ),
        },
        {
            title: 'Reusable configuration with instrument()',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        If you make multiple `query()` calls with the same PostHog configuration, use `instrument()` to
                        configure once and reuse across queries.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import asyncio
                            from posthog import Posthog
                            from posthog.ai.claude_agent_sdk import instrument
                            from claude_agent_sdk import ClaudeAgentOptions

                            posthog = Posthog(
                                "<ph_project_token>",
                                host="<ph_client_api_host>"
                            )

                            ph = instrument(
                                client=posthog,
                                distinct_id="user_123",
                                properties={"app": "my-agent"},
                            )

                            options = ClaudeAgentOptions(max_turns=10)

                            async def main():
                                # All queries share the same PostHog config
                                async for msg in ph.query(prompt="Question 1", options=options):
                                    ...
                                async for msg in ph.query(prompt="Question 2", options=options):
                                    ...

                            asyncio.run(main())
                        `}
                    />

                    <Markdown>You can override any PostHog parameter per-query:</Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            async for msg in ph.query(
                                prompt="...",
                                options=options,
                                posthog_distinct_id="different_user",
                                posthog_properties={"extra": "data"},
                            ):
                                ...
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Tool usage and multi-turn conversations',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            The recommended example above already runs a tool-using query, and \`max_turns\` lets
                            Claude take more than one internal turn before it replies. Inspect the message stream
                            to see each turn and tool call as they happen.
                        `}
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

                            async for message in query(
                                prompt="Read the README and summarize this project",
                                options=options,
                                posthog_client=posthog,
                                posthog_distinct_id="user_123",
                            ):
                                if isinstance(message, AssistantMessage):
                                    for block in message.content:
                                        if isinstance(block, TextBlock):
                                            print(block.text)
                                        elif isinstance(block, ToolUseBlock):
                                            print(f"Tool: {block.name}")
                        `}
                    />

                    <Markdown>
                        {dedent`
                            Across the whole query, PostHog captures:
                            - \`$ai_generation\` events for each LLM turn (with token counts, cost, and cache metrics)
                            - \`$ai_span\` events for each tool use (Read, Glob, Grep, Bash, etc.)
                            - An \`$ai_trace\` event grouping the entire conversation with total cost and latency
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Multi-turn conversations with history',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        For stateful, multi-turn conversations where each follow-up has full context from previous
                        turns, use `PostHogClaudeSDKClient`. This wraps the Claude Agent SDK's `ClaudeSDKClient` and
                        instruments each turn automatically. All turns share a single trace.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            from posthog import Posthog
                            from posthog.ai.claude_agent_sdk import PostHogClaudeSDKClient
                            from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage
                            from claude_agent_sdk.types import TextBlock

                            posthog = Posthog(
                                "<ph_project_token>",
                                host="<ph_client_api_host>"
                            )

                            options = ClaudeAgentOptions(max_turns=5)

                            async with PostHogClaudeSDKClient(
                                options,
                                posthog_client=posthog,
                                posthog_distinct_id="user_123",
                                posthog_properties={"app": "my-agent"},
                            ) as client:
                                # Turn 1
                                await client.query("What is the capital of France?")
                                async for msg in client.receive_response():
                                    if isinstance(msg, AssistantMessage):
                                        for block in msg.content:
                                            if isinstance(block, TextBlock):
                                                print(block.text)

                                # Turn 2 — has full conversation history
                                await client.query("What language do they speak there?")
                                async for msg in client.receive_response():
                                    if isinstance(msg, AssistantMessage):
                                        for block in msg.content:
                                            if isinstance(block, TextBlock):
                                                print(block.text)
                        `}
                    />

                    <Markdown>
                        {dedent`
                            Each \`receive_response()\` cycle emits \`$ai_generation\` events for that turn. When the
                            client disconnects, exiting the \`async with\` block, it emits a single \`$ai_trace\`
                            event covering the entire session with aggregate latency.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const ClaudeAgentSDKInstallation = createInstallation(getClaudeAgentSDKSteps)
