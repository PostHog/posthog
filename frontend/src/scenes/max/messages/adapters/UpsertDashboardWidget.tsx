import { IconDashboard } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { GenericMcpToolRenderer, DataToolRow, type ToolRendererProps } from 'products/posthog_ai/frontend/api/tools'

import { extractDashboard } from './extractors'

/**
 * Dashboard create / update tool calls. v1 is a status line + "View dashboard" CTA (a full
 * dashboard embed is deliberately deferred). Pre-completion or malformed output falls back to
 * the generic card.
 */
export function UpsertDashboardWidget(props: ToolRendererProps): JSX.Element {
    const { message } = props
    const dashboard = message.status === 'completed' ? extractDashboard(message) : null

    if (!dashboard) {
        return <GenericMcpToolRenderer {...props} />
    }

    const to = dashboard.url ?? (dashboard.id !== undefined ? urls.dashboard(dashboard.id) : undefined)

    return (
        <DataToolRow {...props}>
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
        </DataToolRow>
    )
}
