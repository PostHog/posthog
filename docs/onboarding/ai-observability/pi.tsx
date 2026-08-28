import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getPiSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent } = ctx

    return [
        {
            title: 'Prerequisites',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        [Pi](https://github.com/badlogic/pi-mono) is an open-source coding agent that runs in your terminal. The \`@posthog/pi\` extension captures LLM generations, tool executions, and conversation traces as \`$ai_generation\`, \`$ai_span\`, and \`$ai_trace\` events and sends them to PostHog.

                        You need:

                        - [Pi](https://github.com/badlogic/pi-mono) coding agent installed. The extension requires Node.js 22 or later.
                        - A [PostHog account](https://app.posthog.com/signup) with a project token.
                    `}
                </Markdown>
            ),
        },
        {
            title: 'Install the extension',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog extension globally:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pi install npm:@posthog/pi
                        `}
                    />
                    <Markdown>Or install it for the current project:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pi install -l npm:@posthog/pi
                        `}
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
                        Set environment variables with your PostHog project token and host. You can find these in your
                        [PostHog project settings](https://app.posthog.com/settings/project).
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            export POSTHOG_API_KEY="<ph_project_token>"
                            export POSTHOG_HOST="<ph_client_api_host>"
                        `}
                    />
                    <Markdown>Then start Pi as normal:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            pi
                        `}
                    />
                    <Markdown>
                        The extension initializes and captures events for each LLM call, tool execution, and completed
                        agent run.
                    </Markdown>
                    <Blockquote>
                        <Markdown>
                            **Tip:** Add these variables to your shell profile, such as `~/.zshrc` or `~/.bashrc`, so
                            they persist across sessions.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Configuration options',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        Configure the extension with environment variables or a \`~/.pi/agent/posthog.json\` config file. Environment variables take precedence over config file values.

                        | Variable | Default | Description |
                        | --- | --- | --- |
                        | \`POSTHOG_API_KEY\` | _(required)_ | Your PostHog project token |
                        | \`POSTHOG_HOST\` | \`https://us.i.posthog.com\` | PostHog ingestion host |
                        | \`POSTHOG_PRIVACY_MODE\` | \`false\` | When \`true\`, LLM input and output content is not sent to PostHog. Token counts, costs, latency, and model metadata are still captured. |
                        | \`POSTHOG_ENABLED\` | \`true\` | Set to \`false\` to disable the extension |
                        | \`POSTHOG_TRACE_GROUPING\` | \`message\` | \`message\`: one trace per user prompt. \`session\`: group all generations in a session into one trace. |
                        | \`POSTHOG_SESSION_WINDOW_MINUTES\` | \`60\` | Minutes of inactivity before starting a new session window |
                        | \`POSTHOG_PROJECT_NAME\` | Current directory name | Project name included in all events |
                        | \`POSTHOG_AGENT_NAME\` | Agent name | Agent name. Defaults to the project name and detects subagent names when available. |
                        | \`POSTHOG_TAGS\` | _(none)_ | Custom tags added to all events in \`key1:val1,key2:val2\` format |
                        | \`POSTHOG_MAX_ATTRIBUTE_LENGTH\` | \`12000\` | Maximum length for serialized tool input and output attributes |

                        ### Trace grouping modes

                        - **\`message\` (default):** Each user prompt creates a new trace. Multiple LLM turns within one prompt, including tool-use loops, are grouped under the same trace.
                        - **\`session\`:** All generations within a session window are grouped into one trace. A new trace starts after \`POSTHOG_SESSION_WINDOW_MINUTES\` of inactivity.

                        ### Privacy mode

                        When \`POSTHOG_PRIVACY_MODE=true\`, all LLM input and output content, user prompts, tool inputs, and tool outputs are redacted. Token counts, costs, latency, and model metadata are still captured.

                        Even with privacy mode off, sensitive keys in tool inputs and outputs, such as \`api_key\`, \`token\`, \`secret\`, \`password\`, and \`authorization\`, are redacted.

                        ### What gets captured

                        The extension captures three types of events:

                        - **\`$ai_generation\`:** Each LLM call, including model, provider, token usage, cost, latency, and input and output messages in [OpenAI chat format](https://posthog.com/docs/ai-observability/generations).
                        - **\`$ai_span\`:** Each tool execution (read, write, edit, bash, and others), including tool name, input parameters, output result, and duration. [Learn more about spans](https://posthog.com/docs/ai-observability/spans).
                        - **\`$ai_trace\`:** Completed agent runs with aggregated token totals and latency. [Learn more about traces](https://posthog.com/docs/ai-observability/traces).
                    `}
                </Markdown>
            ),
        },
    ]
}

export const PiInstallation = createInstallation(getPiSteps)
