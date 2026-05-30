import { IconCheck, IconWarning, IconWrench, IconX } from '@posthog/icons'
import { LemonCollapse, LemonTag, Spinner } from '@posthog/lemon-ui'

import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { ToolInvocationStatus } from '../../types/sandboxStreamTypes'
import { MessageTemplate } from '../MessageTemplate'

function statusBadge(status: ToolInvocationStatus): JSX.Element {
    switch (status) {
        case 'completed':
            return (
                <LemonTag type="success" icon={<IconCheck />} size="small">
                    Completed
                </LemonTag>
            )
        case 'failed':
            return (
                <LemonTag type="danger" icon={<IconX />} size="small">
                    Failed
                </LemonTag>
            )
        case 'in_progress':
            return (
                <LemonTag type="primary" size="small">
                    <Spinner className="mr-1" />
                    Running
                </LemonTag>
            )
        default:
            return (
                <LemonTag type="muted" size="small">
                    Pending
                </LemonTag>
            )
    }
}

function prettyJson(value: unknown): string {
    try {
        return JSON.stringify(value, null, 2)
    } catch {
        return String(value)
    }
}

function renderContentBlocks(blocks: unknown[]): string {
    return blocks
        .map((block) => {
            if (block && typeof block === 'object' && 'type' in block && (block as { type: string }).type === 'text') {
                const text = (block as { text?: string }).text
                if (typeof text === 'string') {
                    return text
                }
            }
            return prettyJson(block)
        })
        .join('\n')
}

/**
 * Catch-all renderer for MCP tool calls that have no wired adapter (user-installed MCPs,
 * unknown servers, inner tools we haven't built a custom card for, or a malformed
 * single-exec command). Renders a generic, greppable tool card so every enabled tool
 * still shows something sensible. See docs/internal/posthog-ai-migration/03_RICH_UI.md §3.4.
 */
export function FallbackMcpToolRenderer({ message }: McpToolRendererProps): JSX.Element {
    const headerLabel = message.title || message.innerToolName || message.rawToolName
    const errorMessage =
        message.status === 'failed' && typeof message.error?.message === 'string' ? message.error.message : null

    const accordionPanels = [
        message.rawInput && Object.keys(message.rawInput).length > 0
            ? {
                  key: 'input',
                  header: 'Input',
                  content: (
                      <pre className="text-xs whitespace-pre-wrap break-words">{prettyJson(message.rawInput)}</pre>
                  ),
              }
            : null,
        message.content && message.content.length > 0
            ? {
                  key: 'content',
                  header: 'Output',
                  content: (
                      <pre className="text-xs whitespace-pre-wrap break-words">
                          {renderContentBlocks(message.content)}
                      </pre>
                  ),
              }
            : null,
        message.rawOutput !== undefined
            ? {
                  key: 'rawOutput',
                  header: 'Raw output',
                  content: (
                      <pre className="text-xs whitespace-pre-wrap break-words">{prettyJson(message.rawOutput)}</pre>
                  ),
              }
            : null,
    ].filter((panel): panel is { key: string; header: string; content: JSX.Element } => panel !== null)

    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5">
                    <IconWrench className="text-lg text-secondary flex-shrink-0" />
                    <span className="font-medium truncate min-w-0 flex-1">{headerLabel}</span>
                    {statusBadge(message.status)}
                </div>
                {errorMessage && (
                    <div className="flex items-start gap-1.5 text-danger">
                        <IconWarning className="text-lg flex-shrink-0" />
                        <span className="text-sm break-words">{errorMessage}</span>
                    </div>
                )}
                {accordionPanels.length > 0 && <LemonCollapse multiple panels={accordionPanels} size="small" />}
            </div>
        </MessageTemplate>
    )
}
