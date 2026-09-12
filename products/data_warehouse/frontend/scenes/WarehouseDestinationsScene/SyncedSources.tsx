import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

// Enough names to see what a destination serves at a glance; the rest go behind a count, so one
// destination shared by dozens of sources does not push every other row off the screen.
const NAMES_SHOWN = 3

export interface SyncedSourcesProps {
    destination: ExternalDataDestinationApi
}

export function SyncedSources({ destination }: SyncedSourcesProps): JSX.Element {
    const sources = destination.synced_sources ?? []

    if (sources.length === 0) {
        return <span className="text-muted">Nothing yet</span>
    }

    const shown = sources.slice(0, NAMES_SHOWN)
    const hidden = sources.slice(NAMES_SHOWN)

    return (
        <div className="flex flex-wrap gap-1 items-center">
            {shown.map((source) => (
                <Tooltip
                    key={source.id}
                    title={
                        source.via_table_override
                            ? 'Only some of this source’s tables sync here, through their own destinations'
                            : 'Every table on this source syncs here'
                    }
                >
                    <Link to={urls.dataWarehouseSource(source.id, 'destinations')}>
                        <LemonTag type={source.via_table_override ? 'muted' : 'default'}>{source.name}</LemonTag>
                    </Link>
                </Tooltip>
            ))}
            {hidden.length > 0 && (
                <Tooltip title={hidden.map((source) => source.name).join(', ')}>
                    <span className="text-muted text-xs">and {hidden.length} more</span>
                </Tooltip>
            )}
        </div>
    )
}
