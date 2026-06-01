import { IconCheck, IconWarning, IconWrench } from '@posthog/icons'
import { LemonCollapse, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { McpToolRendererProps } from '../mcpToolRegistry'
import { MessageTemplate } from './MessageTemplate'

/** Pretty-prints accumulated ACP `content[]` — text frames inline, everything else as JSON. */
function renderContentBlocks(content: unknown[]): string {
    return content
        .map((block) => {
            if (block && typeof block === 'object' && 'text' in block) {
                return String((block as { text: unknown }).text)
            }
            return JSON.stringify(block, null, 2)
        })
        .join('\n')
}

function statusBadge(status: McpToolRendererProps['message']['status']): JSX.Element {
    if (status === 'in_progress' || status === 'pending') {
        return <Spinner className="text-sm" />
    }
    if (status === 'failed') {
        return <IconWarning className="text-danger text-sm" />
    }
    return <IconCheck className="text-success text-sm" />
}

/**
 * Catch-all renderer for any MCP tool call not yet wired through a custom adapter — user-installed
 * MCPs, unknown inner tools, malformed `exec` commands. Renders a generic, greppable tool card so
 * the registry can ship incrementally. See docs/internal/posthog-ai-migration/03_RICH_UI.md § 3.4.
 */
export function FallbackMcpToolRenderer({ message }: McpToolRendererProps): JSX.Element {
    const headerLabel = message.title || message.innerToolName || message.rawToolName || 'Tool call'
    const contentText = message.content.length > 0 ? renderContentBlocks(message.content) : ''
    const outputText =
        message.rawOutput !== undefined && message.rawOutput !== null ? JSON.stringify(message.rawOutput, null, 2) : ''

    return (
        <MessageTemplate
            type="ai"
            header={
                <div className="flex items-center gap-1.5 text-sm text-secondary mb-1">
                    <IconWrench className="text-base" />
                    <span className="font-medium text-default">{headerLabel}</span>
                    {statusBadge(message.status)}
                </div>
            }
        >
            <div className="flex flex-col gap-2">
                {message.status === 'failed' && message.error?.message && (
                    <div className="text-danger text-sm">{message.error.message}</div>
                )}
                <LemonCollapse
                    size="small"
                    panels={[
                        {
                            key: 'input',
                            header: 'Input',
                            content: (
                                <CodeSnippet language={Language.JSON} compact>
                                    {JSON.stringify(message.innerInput ?? message.rawInput, null, 2)}
                                </CodeSnippet>
                            ),
                        },
                        contentText
                            ? {
                                  key: 'content',
                                  header: 'Output',
                                  content: (
                                      <CodeSnippet language={Language.Text} compact>
                                          {contentText}
                                      </CodeSnippet>
                                  ),
                              }
                            : null,
                        outputText
                            ? {
                                  key: 'raw-output',
                                  header: 'Raw output',
                                  content: (
                                      <CodeSnippet language={Language.JSON} compact>
                                          {outputText}
                                      </CodeSnippet>
                                  ),
                              }
                            : null,
                    ]}
                />
            </div>
        </MessageTemplate>
    )
}
