import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

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
                            background to send the data. You can also use LLM analytics with other SDKs or our API, but
                            you will need to capture the data in the right format. See the schema in the [manual capture
                            section](https://posthog.com/docs/llm-analytics/installation/manual-capture) for more
                            details.
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
                        Initialize PostHog with your project token and host from [your project
                        settings](https://app.posthog.com/settings/project), then use the PostHog `query()` wrapper as a
                        drop-in replacement for `claude_agent_sdk.query()`. This automatically captures
                        `$ai_generation`, `$ai_span`, and `$ai_trace` events.
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
                                    permission_mode="plan",
                                )

                                async for message in query(
                                    prompt="Tell me a fun fact about hedgehogs",
                                    options=options,
                                    posthog_client=posthog,
                                    posthog_distinct_id="user_123", # optional
                                    posthog_trace_id="trace_123", # optional
                                    posthog_properties={"conversation_id": "abc123"}, # optional
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
                            - All original messages are yielded unchanged — the wrapper is fully transparent.
                            - If you want to capture LLM events anonymously, **don't** pass a distinct ID. See our docs on [anonymous vs identified events](https://posthog.com/docs/data/anonymous-vs-identified-events) to learn more.
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

                    <Markdown>
                        {dedent`
                            You can override any PostHog parameter per-query:

                            \`\`\`python
                            async for msg in ph.query(
                                prompt="...",
                                options=options,
                                posthog_distinct_id="different_user",
                                posthog_properties={"extra": "data"},
                            ):
                                ...
                            \`\`\`
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Tool usage and multi-turn conversations',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        PostHog captures the full trace hierarchy for multi-turn agent conversations with tool calls.
                        Each tool use is captured as an `$ai_span` event linked to its parent generation.
                    </Markdown>

                    <CodeBlock
                        language="python"
                        code={dedent`
                            import asyncio
                            from posthog import Posthog
                            from posthog.ai.claude_agent_sdk import query
                            from claude_agent_sdk import ClaudeAgentOptions, AssistantMessage, TextBlock, ToolUseBlock

                            posthog = Posthog(
                                "<ph_project_token>",
                                host="<ph_client_api_host>"
                            )

                            options = ClaudeAgentOptions(
                                max_turns=10,
                                allowed_tools=["Read", "Glob", "Grep", "Bash"],
                                permission_mode="bypassPermissions",
                                cwd="/path/to/your/project",
                            )

                            async def main():
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

                            asyncio.run(main())
                            posthog.shutdown()
                        `}
                    />

                    <Markdown>
                        {dedent`
                            This captures:
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
                            Each \`receive_response()\` cycle emits \`$ai_generation\` events for that turn. When the client disconnects (exiting the \`async with\` block), a single \`$ai_trace\` event is emitted covering the entire session with aggregate latency.
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const ClaudeAgentSDKInstallation = createInstallation(getClaudeAgentSDKSteps)
