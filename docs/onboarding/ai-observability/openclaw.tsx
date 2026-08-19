import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getOpenClawSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Blockquote, dedent } = ctx

    return [
        {
            title: 'Prerequisites',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        [OpenClaw](https://github.com/openclaw/openclaw) is a self-hosted AI assistant gateway that connects messaging platforms such as Telegram, Slack, Discord, and WebChat to AI models. The [\`@posthog/openclaw\`](https://github.com/PostHog/posthog-openclaw) plugin captures LLM generations, tool executions, and conversation traces as \`$ai_generation\`, \`$ai_span\`, and \`$ai_trace\` events.

                        You need:

                        - A running [OpenClaw](https://github.com/openclaw/openclaw) gateway. The PostHog plugin supports Node.js 20 or later.
                        - A [PostHog account](https://app.posthog.com/signup) with a project token.
                    `}
                </Markdown>
            ),
        },
        {
            title: 'Install the PostHog plugin',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the [`@posthog/openclaw`](https://github.com/PostHog/posthog-openclaw) plugin with the
                        OpenClaw CLI:
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            openclaw plugins install @posthog/openclaw
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Configure the plugin',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Add the PostHog plugin to your OpenClaw config file (`~/.openclaw/openclaw.json` or
                        `openclaw.yaml`):
                    </Markdown>
                    <CodeBlock
                        language="json"
                        code={dedent`
                            {
                              "plugins": {
                                "entries": {
                                  "posthog": {
                                    "enabled": true,
                                    "config": {
                                      "apiKey": "<ph_project_token>",
                                      "host": "<ph_client_api_host>"
                                    }
                                  }
                                }
                              },
                              "diagnostics": {
                                "enabled": true
                              }
                            }
                        `}
                    />
                    <Markdown>
                        You can find your project token and host in your [PostHog project
                        settings](https://app.posthog.com/settings/project).
                    </Markdown>
                    <Blockquote>
                        <Markdown>
                            **Note:** `diagnostics.enabled` must be `true` to capture trace-level (`$ai_trace`) events.
                            Generation and span events work without it.
                        </Markdown>
                    </Blockquote>
                </>
            ),
        },
        {
            title: 'Start the gateway',
            badge: 'required',
            content: (
                <>
                    <Markdown>Start or restart the OpenClaw gateway for the plugin to take effect:</Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            node openclaw.mjs gateway
                        `}
                    />
                    <Markdown>
                        The PostHog plugin initializes on startup. When users send messages through a connected channel,
                        AI Observability events are captured and sent to PostHog.
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
                        All options go under the \`config\` key inside the \`posthog\` plugin entry:

                        | Option | Type | Default | Description |
                        | --- | --- | --- | --- |
                        | \`apiKey\` | \`string\` | _(required)_ | Your PostHog project token |
                        | \`host\` | \`string\` | \`https://us.i.posthog.com\` | PostHog ingestion host |
                        | \`privacyMode\` | \`boolean\` | \`false\` | When enabled, message content is not sent to PostHog. Token counts, latency, model information, and errors are still captured. |
                        | \`traceGrouping\` | \`"message"\` or \`"session"\` | \`"message"\` | \`"message"\`: one trace per LLM call cycle. \`"session"\`: groups all generations in a conversation into one trace. |
                        | \`sessionWindowMinutes\` | \`number\` | \`60\` | Minutes of inactivity before starting a new session window. Applies in both trace grouping modes. |

                        ### Trace grouping modes

                        - **\`"message"\` (default):** Each agent invocation gets its own trace. Tool-use iterations within one invocation share the same trace.
                        - **\`"session"\`:** All generations within a conversation window are grouped into one trace. A new trace starts after \`sessionWindowMinutes\` of inactivity. Use this for chat channels where per-message traces fragment conversation flow.

                        ### What gets captured

                        The plugin captures three types of events:

                        - **\`$ai_generation\`:** Each LLM call, including model, provider, token usage, cost, latency, and input and output messages in [OpenAI chat format](https://posthog.com/docs/ai-observability/generations).
                        - **\`$ai_span\`:** Each tool execution, including tool name, input parameters, output result, duration, and parent generation. [Learn more about spans](https://posthog.com/docs/ai-observability/spans).
                        - **\`$ai_trace\`:** Completed message cycles with aggregated token totals and latency. [Learn more about traces](https://posthog.com/docs/ai-observability/traces).
                    `}
                </Markdown>
            ),
        },
    ]
}

export const OpenClawInstallation = createInstallation(getOpenClawSteps)
