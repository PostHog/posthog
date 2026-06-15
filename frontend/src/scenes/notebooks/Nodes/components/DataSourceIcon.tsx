import { IconDatabase, IconPiggyBank } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

export function DataSourceIcon({ source }: { source: 'revenue-analytics' | 'properties' | null }): JSX.Element | null {
    if (!source) {
        return null
    }

    if (source === 'revenue-analytics') {
        return (
            <Tooltip title="From Revenue analytics">
                <IconPiggyBank className="w-3 h-3 text-muted" data-attr="piggybank-icon" />
            </Tooltip>
        )
    }

    return (
        <Tooltip title="From group properties">
            <IconDatabase className="w-3 h-3 text-muted" data-attr="database-icon" />
        </Tooltip>
    )
}
