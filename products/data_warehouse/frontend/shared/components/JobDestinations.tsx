import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DESTINATION_ICON_MAP, destinationTypeLabel } from './DestinationIcon'
import { destinationTarget } from './DestinationList'

export interface JobDestinationsProps {
    /** Snapshotted on the run when it started. Empty on runs that predate destinations. */
    destinationIds: readonly string[]
    /** Every destination the project has, so ids can be named. Absent until the lookup mounts. */
    destinationsById?: Record<string, ExternalDataDestinationApi>
    /** True while `destinationsById` is still being fetched, so an id is not yet unknown. */
    loading?: boolean
}

function tooltipFor(destination: ExternalDataDestinationApi): string {
    const target = destinationTarget(destination)
    return target ? `${destination.name} — ${target}` : destination.name
}

/** Where one run delivered, as a logo each. */
export function JobDestinations({ destinationIds, destinationsById = {}, loading }: JobDestinationsProps): JSX.Element {
    // A run from before destinations existed wrote to the warehouse and recorded nothing, so it
    // has nothing to show rather than nothing to say.
    if (destinationIds.length === 0) {
        return <span className="text-muted">—</span>
    }

    const known = destinationIds.map((id) => destinationsById[id]).filter(Boolean)

    if (known.length === 0) {
        // A table renders rows before the lookup logic has mounted, so an id that is not in the
        // map yet is not the same as one that will never be there.
        return loading || Object.keys(destinationsById).length === 0 ? (
            <span className="text-muted">—</span>
        ) : (
            // Deleting a destination leaves the runs that used it pointing at nothing.
            <Tooltip title="This run delivered to a destination that no longer exists">
                <span className="text-muted">{destinationIds.length} removed</span>
            </Tooltip>
        )
    }

    return (
        <div className="flex items-center gap-1">
            {known.map((destination) => (
                <Tooltip key={destination.id} title={tooltipFor(destination)}>
                    <span className="flex items-center justify-center size-5">
                        <img
                            src={DESTINATION_ICON_MAP[destination.type]}
                            alt={destinationTypeLabel(destination.type)}
                            className="max-w-full max-h-full"
                        />
                    </span>
                </Tooltip>
            ))}
        </div>
    )
}
