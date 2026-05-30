import { IconCheck, IconDashboard } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { MessageTemplate } from '../MessageTemplate'
import { asObject, isCompleted, toolInput } from './extractors'

/**
 * Renders `dashboard-create` / `dashboard-update`. v1 is a status line plus a "View dashboard"
 * CTA — the full embedded dashboard is deferred. The dashboard id / url come off `rawOutput`.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §4.
 */
export function UpsertDashboardAdapter({ message }: McpToolRendererProps): JSX.Element {
    const input = toolInput(message)
    const name = typeof input.name === 'string' ? input.name : undefined
    const out = asObject(message.rawOutput)
    const url = typeof out?.url === 'string' ? out.url : null
    const id = typeof out?.id === 'number' ? out.id : typeof out?.id === 'string' ? Number(out.id) : null
    const dashboardUrl = url ?? (id && !Number.isNaN(id) ? urls.dashboard(id) : null)
    const completed = isCompleted(message)

    return (
        <MessageTemplate type="ai">
            <div className="flex items-center gap-2">
                <IconDashboard className="text-lg text-secondary flex-shrink-0" />
                <span className="font-medium truncate min-w-0 flex-1">{name ?? 'Dashboard'}</span>
                {completed ? <IconCheck className="text-success flex-shrink-0" /> : <Spinner />}
                {completed && dashboardUrl && (
                    <LemonButton
                        to={dashboardUrl}
                        targetBlank
                        icon={<IconOpenInNew />}
                        size="xsmall"
                        tooltip="View dashboard"
                    />
                )}
            </div>
        </MessageTemplate>
    )
}
