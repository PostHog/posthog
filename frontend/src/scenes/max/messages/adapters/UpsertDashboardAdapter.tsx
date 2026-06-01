import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { FallbackMcpToolRenderer } from '../FallbackMcpToolRenderer'
import { MessageTemplate } from '../MessageTemplate'
import { extractDashboard } from './extractors'

/**
 * Dashboard create / update tool calls. v1 is a status line + "View dashboard" CTA (full embed is
 * deferred per 03_RICH_UI.md § 4.2). Pre-completion or malformed output falls back to the generic
 * card. See docs/internal/posthog-ai-migration/03_RICH_UI.md § 4.2 and MCP_TOOLS.md `upsert_dashboard`.
 */
export function UpsertDashboardAdapter({ message, isLastInGroup }: McpToolRendererProps): JSX.Element {
    const dashboard = message.status === 'completed' ? extractDashboard(message) : null

    if (!dashboard) {
        return <FallbackMcpToolRenderer message={message} isLastInGroup={isLastInGroup} />
    }

    const to = dashboard.url ?? (dashboard.id !== undefined ? urls.dashboard(dashboard.id) : undefined)

    return (
        <MessageTemplate type="ai">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                    <IconDashboard className="text-base" />
                    <span className="font-medium">{dashboard.name || 'Dashboard ready'}</span>
                </div>
                {to && (
                    <LemonButton to={to} targetBlank icon={<IconOpenInNew />} size="xsmall" tooltip="Open dashboard">
                        View dashboard
                    </LemonButton>
                )}
            </div>
        </MessageTemplate>
    )
}
