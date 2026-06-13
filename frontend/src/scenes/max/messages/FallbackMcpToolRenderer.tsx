import { IconCheck, IconWarning, IconWrench } from '@posthog/icons'
import { LemonCollapse, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { McpToolRendererProps } from '../mcpToolRegistry'
import { MessageTemplate } from './MessageTemplate'

/**
 * Extracts displayable text from one ACP tool-call content block. ACP nests the real ContentBlock
 * under a `{ type: 'content', content: { type: 'text', text } }` envelope, so unwrap that first;
 * flat `{ type: 'text', text }` blocks are read directly. Non-text blocks fall back to pretty JSON.
 */
export function contentBlockText(block: unknown): string {
    if (!block || typeof block !== 'object') {
        return JSON.stringify(block, null, 2)
    }
    const inner =
        (block as { type?: unknown }).type === 'content' && 'content' in block
            ? (block as { content: unknown }).content
            : block
    if (inner && typeof inner === 'object' && 'text' in inner) {
        return String((inner as { text: unknown }).text)
    }
    return JSON.stringify(block, null, 2)
}

/** Pretty-prints accumulated ACP `content[]` — text frames inline, everything else as JSON. */
export function renderContentBlocks(content: unknown[]): string {
    return content.map(contentBlockText).join('\n')
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
 * the registry can ship incrementally.
 */
export function FallbackMcpToolRenderer({ message, icon, displayName }: McpToolRendererProps): JSX.Element {
    const headerLabel = message.title || message.innerToolName || displayName || message.rawToolName || 'Tool call'
    // The registry entry contributes the icon (friendly built-in icons, data-tool icons); fall back to
    // the generic wrench only when the renderer is mounted without a resolved entry.
    const headerIcon = icon ?? <IconWrench className="text-base" />
    const contentText = message.content.length > 0 ? renderContentBlocks(message.content) : ''
    const outputText =
        message.rawOutput !== undefined && message.rawOutput !== null ? JSON.stringify(message.rawOutput, null, 2) : ''

    return (
        <MessageTemplate
            type="ai"
            header={
                <div className="flex items-center gap-1.5 text-sm text-secondary mb-1">
                    <span className="text-base flex items-center">{headerIcon}</span>
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
