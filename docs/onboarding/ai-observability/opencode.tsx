import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getOpenCodeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent } = ctx

    return [
        {
            title: 'Prerequisites',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        [OpenCode](https://opencode.ai) is an open-source AI coding agent that runs in your terminal. The [\`@posthog/opencode\`](https://github.com/PostHog/posthog-opencode) plugin captures LLM generations, tool executions, and conversation traces as \`$ai_generation\`, \`$ai_span\`, and \`$ai_trace\` events and sends them to PostHog.

                        You need:

                        - [OpenCode](https://opencode.ai/docs) installed
                        - A [PostHog account](https://app.posthog.com/signup) with a project token
                    `}
                </Markdown>
            ),
        },
        {
            title: 'Install the plugin',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add `@posthog/opencode` to the `plugin` array in your `opencode.json` file:</Markdown>
                    <CodeBlock
                        language="json"
                        code={dedent`
                            {
                              "$schema": "https://opencode.ai/config.json",
                              "plugin": ["@posthog/opencode"]
                            }
                        `}
                    />
                    <Markdown>
                        Use `opencode.json` in your project root for a project-level install, or
                        `~/.config/opencode/opencode.json` for a global install. OpenCode installs the package when it
                        starts and caches it in `~/.cache/opencode/node_modules/`.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Set environment variables with your PostHog project token and host. You can find both in your
                        [PostHog project settings](https://app.posthog.com/settings/project).
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            export POSTHOG_API_KEY="<ph_project_token>"
                            export POSTHOG_HOST="<ph_client_api_host>"
                        `}
                    />
                    <Blockquote>
                        <Markdown>
                            **Tip:** Add these variables to your shell profile, such as `~/.zshrc` or `~/.bashrc`, so
                            they persist across sessions.
                        </Markdown>
                    </Blockquote>
                    <Markdown>If `POSTHOG_API_KEY` is not set, the plugin does not capture or send events.</Markdown>
                </>
            ),
        },
        {
            title: 'Run a session',
            badge: 'required',
            content: (
                <>
                    <Markdown>Start OpenCode as normal and use it for a task:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            opencode
                        `}
                    />
                    <Markdown>
                        The plugin initializes and captures events for each LLM call, tool execution, and completed
                        prompt.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configuration options',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        Configure the plugin with environment variables:

                        | Variable | Default | Description |
                        | --- | --- | --- |
                        | \`POSTHOG_API_KEY\` | _(required)_ | Your PostHog project token |
                        | \`POSTHOG_HOST\` | \`https://us.i.posthog.com\` | PostHog ingestion host |
                        | \`POSTHOG_PRIVACY_MODE\` | \`false\` | When \`true\`, the plugin does not send LLM content, prompts, or tool inputs and outputs. Token counts, costs, latency, and model metadata are still captured. |
                        | \`POSTHOG_ENABLED\` | \`true\` | Set to \`false\` to disable the plugin |
                        | \`POSTHOG_DISTINCT_ID\` | Machine hostname | Distinct ID included in all events |
                        | \`POSTHOG_PROJECT_NAME\` | Current directory name | Project name included in all events |
                        | \`POSTHOG_TAGS\` | _(none)_ | Custom tags added to all events in \`key1:val1,key2:val2\` format |
                        | \`POSTHOG_MAX_ATTRIBUTE_LENGTH\` | \`12000\` | Maximum length for serialized tool input and output attributes |

                        ### Privacy mode

                        When \`POSTHOG_PRIVACY_MODE=true\`, all LLM content, user prompts, tool inputs, and tool outputs are redacted. Token counts, costs, latency, and model metadata are still captured.

                        The plugin always redacts sensitive keys matching terms such as \`api_key\`, \`token\`, \`secret\`, \`password\`, \`authorization\`, \`credential\`, and \`private_key\`, regardless of privacy mode.

                        ### What gets captured

                        The plugin captures three types of events:

                        - **\`$ai_generation\`:** Each LLM call, including model, provider, token usage, cost, stop reason, and input and output messages in [OpenAI chat format](https://posthog.com/docs/ai-observability/generations).
                        - **\`$ai_span\`:** Each tool execution, including tool name, input parameters, output result, duration, parent generation, and error details. [Learn more about spans](https://posthog.com/docs/ai-observability/spans).
                        - **\`$ai_trace\`:** Each completed prompt, including aggregated token totals, latency, input and output state, and error status. [Learn more about traces](https://posthog.com/docs/ai-observability/traces).
                    `}
                </Markdown>
            ),
        },
    ]
}

export const OpenCodeInstallation = createInstallation(getOpenCodeSteps)
