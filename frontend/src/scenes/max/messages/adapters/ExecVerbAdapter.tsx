import { IconWrench } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { ToolCardHeader } from '../../components/ToolCardHeader'
import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { MessageTemplate } from '../MessageTemplate'
import { extractContentText, extractExecVerbHeader } from './extractors'

/**
 * Renders the single-exec discovery verbs (`tools` / `search` / `info` / `schema`) — the
 * introspection calls the model makes against the dispatcher. One shared adapter resolves a
 * one-line header from the raw `command` and tucks the catalog/match output into a collapsed
 * accordion. The malformed `__posthog_exec_unknown__` key is NOT registered here — it falls
 * through to `FallbackMcpToolRenderer`.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §4.1.
 */
export function ExecVerbAdapter({ message }: McpToolRendererProps): JSX.Element {
    const header = extractExecVerbHeader(message)
    const output = extractContentText(message.content)

    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2">
                <ToolCardHeader
                    status={message.status}
                    icon={<IconWrench className="text-secondary" />}
                    label={header}
                />
                {output && (
                    <LemonCollapse
                        size="small"
                        panels={[
                            {
                                key: 'output',
                                header: 'Output',
                                content: <pre className="text-xs whitespace-pre-wrap break-words">{output}</pre>,
                            },
                        ]}
                    />
                )}
            </div>
        </MessageTemplate>
    )
}
