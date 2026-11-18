import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getClaudeCodeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent } = ctx

    return [
        {
            title: 'Prerequisites',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) is Anthropic's agentic coding tool that runs in your terminal. The [PostHog plugin](https://github.com/PostHog/ai-plugin) captures every Claude Code session as structured AI Observability events: generations, tool executions, and traces. You can install the full plugin, or a second plugin that only captures sessions.

                            This is useful for:

                            - **Transparency and auditability:** See what Claude did in each session, including every tool call and LLM invocation.
                            - **Cost tracking:** Monitor token usage and costs across your team.
                            - **Team sharing:** Give your team visibility into coding sessions without sharing terminal access.
                            - **Debugging:** Trace through multi-step agent runs to understand what happened.

                            You need:

                            - [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed
                            - A [PostHog account](https://app.posthog.com/signup) with a project token
                        `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Install the PostHog plugin',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog plugin for Claude Code:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            claude plugin install posthog
                        `}
                    />
                    <Markdown>
                        This adds a `SessionEnd` hook that parses your session logs and sends events to PostHog when
                        each session finishes. The plugin also loads PostHog skills, slash commands, and the PostHog MCP
                        server into every session.
                    </Markdown>
                    <Markdown>
                        {dedent`
                            ### Install session capture on its own

                            To capture sessions without the skills, slash commands, and MCP server, install PostHog session capture instead of the full plugin. It registers the \`SessionEnd\` hook and nothing else, so it adds nothing to what Claude reads at the start of each session.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            claude plugin marketplace add PostHog/ai-plugin
                            claude plugin install posthog-telemetry@posthog
                        `}
                    />
                    <Markdown>
                        Both plugins send the same `$ai_generation`, `$ai_span`, and `$ai_trace` events, and they read
                        the same environment variables. PostHog session capture needs the Python standard library only.
                    </Markdown>
                    <Blockquote>
                        <Markdown>
                            **Note:** Install one or the other. Both register the same hook, so both upload every
                            session. PostHog keeps one copy of each event, but the upload happens twice. To switch,
                            remove the one you no longer want with `claude plugin uninstall`.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Set environment variables with your PostHog project token and enable the integration. You can
                        find your project token in your [PostHog project
                        settings](https://app.posthog.com/settings/project).
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            export POSTHOG_API_KEY="<ph_project_token>"
                            export POSTHOG_LLMA_CC_ENABLED="true"
                        `}
                    />
                    <Blockquote>
                        <Markdown>
                            **Tip:** Add these variables to your shell profile, such as `~/.zshrc` or `~/.bashrc`, so
                            they persist across sessions.
                        </Markdown>
                    </Blockquote>
                    <Markdown>
                        Alternatively, configure them in your Claude Code settings file (`~/.claude/settings.json` or
                        `.claude/settings.local.json`):
                    </Markdown>
                    <CodeBlock
                        language="json"
                        code={dedent`
                            {
                              "env": {
                                "POSTHOG_API_KEY": "<ph_project_token>",
                                "POSTHOG_LLMA_CC_ENABLED": "true"
                              }
                            }
                        `}
                    />
                    <Markdown>If you use PostHog EU, set the host as well:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            export POSTHOG_HOST="https://eu.i.posthog.com"
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Run a session',
            badge: 'required',
            content: (
                <>
                    <Markdown>Start Claude Code as normal and use it for a task:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            claude
                        `}
                    />
                    <Markdown>
                        When the session ends, the hook parses the session log file and sends events to PostHog. No
                        changes to your workflow are needed.
                    </Markdown>
                    <Markdown>
                        With the full plugin installed, check the status of the last send from within Claude Code:
                    </Markdown>
                    <CodeBlock
                        language="text"
                        code={dedent`
                            /posthog:llma-cc-status
                        `}
                    />
                    <Markdown>Either plugin writes the status to `~/.claude/posthog-llma-status.json`.</Markdown>
                </>
            ),
        },
        {
            title: 'Configuration options',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            All configuration is done with environment variables:

                            | Variable | Default | Description |
                            | --- | --- | --- |
                            | \`POSTHOG_API_KEY\` | _(required)_ | Your PostHog project token |
                            | \`POSTHOG_LLMA_CC_ENABLED\` | \`false\` | Set to \`true\` to enable the integration |
                            | \`POSTHOG_HOST\` | \`https://us.i.posthog.com\` | PostHog ingestion host |
                            | \`POSTHOG_LLMA_PRIVACY_MODE\` | \`false\` | When \`true\`, LLM input and output content is not sent to PostHog. Token counts, costs, latency, and model metadata are still captured. |
                            | \`POSTHOG_LLMA_DISTINCT_ID\` | git user email | Distinct ID for events. Falls back to \`claude-code:{session_id}\` if no git email is found. |
                            | \`POSTHOG_LLMA_TRACE_GROUPING\` | \`session\` | \`session\`: one trace per Claude Code session. \`message\`: one trace per user prompt. |
                            | \`POSTHOG_LLMA_MAX_ATTRIBUTE_LENGTH\` | \`12000\` | Maximum character length for serialized tool input and output attributes |

                            ### Trace grouping modes

                            - **\`session\` (default):** All generations and tool executions within a Claude Code session are grouped into one trace. Use this to understand complete coding sessions.
                            - **\`message\`:** Each user prompt creates a separate trace. Multiple LLM turns within one prompt, including tool-use loops, are grouped under the same trace. Use this to analyze individual interactions.

                            ### Privacy mode

                            When \`POSTHOG_LLMA_PRIVACY_MODE=true\`, all LLM input and output content, user prompts, tool inputs, and tool outputs are redacted. Token counts, costs, latency, and model metadata are still captured without exposing code or conversations.

                            ### Ingest past sessions

                            To send data from Claude Code sessions that happened before you set up capture, use the ingestion command below. It ships with the full plugin.
                        `}
                    </Markdown>
                    <CodeBlock
                        language="text"
                        code={dedent`
                            /posthog:llma-cc-ingest
                        `}
                    />
                    <Markdown>
                        PostHog session capture ships no slash commands. To backfill with it, clone the repository and
                        run the ingestion script. List the recent sessions first, then send one:
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            git clone --depth 1 https://github.com/PostHog/ai-plugin.git
                            python3 ai-plugin/telemetry/scripts/llma_cc_ingest.py --list
                            python3 ai-plugin/telemetry/scripts/llma_cc_ingest.py <session-id>
                        `}
                    />
                    <Markdown>
                        {dedent`
                            ### What gets captured

                            Both plugins capture three types of events:

                            - **\`$ai_generation\`:** Each LLM call, including model, provider, token usage (input, output, cache read, and cache creation), stop reason, and input and output messages in [OpenAI chat format](https://posthog.com/docs/ai-observability/generations).
                            - **\`$ai_span\`:** Each tool execution (Bash, Read, Write, Edit, Grep, Glob, MCP tools, and others), including tool name, input parameters, output result, duration, and error information. [Learn more about spans](https://posthog.com/docs/ai-observability/spans).
                            - **\`$ai_trace\`:** Completed sessions or prompts, depending on grouping mode, with aggregated token totals and latency. [Learn more about traces](https://posthog.com/docs/ai-observability/traces).
                        `}
                    </Markdown>
                </>
            ),
        },
    ]
}

export const ClaudeCodeInstallation = createInstallation(getClaudeCodeSteps)
