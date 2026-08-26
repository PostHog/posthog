import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { schemaDestinationsLogic } from './schemaDestinationsLogic'

export interface DestinationsSectionProps {
    schemaId: string
}

export function DestinationsSection({ schemaId }: DestinationsSectionProps): JSX.Element {
    const logic = schemaDestinationsLogic({ schemaId })
    const { destinations, destinationsLoading, draftDestinationIds, isOverriding, overrideLoading, canSave } =
        useValues(logic)
    const { toggleDestination, startOverriding, save, clearOverride } = useActions(logic)

    if (destinationsLoading) {
        return <LemonSkeleton className="w-full h-32" />
    }

    if (destinations.length === 0) {
        return (
            <LemonBanner type="info">
                No destinations set up yet. Add one in project settings to sync this table somewhere alongside the
                PostHog warehouse.
            </LemonBanner>
        )
    }

    if (!isOverriding) {
        return (
            <div className="deprecated-space-y-4">
                <LemonBanner type="info">
                    This table syncs to whatever its source is set to. Give it its own destinations to change that.
                </LemonBanner>
                <div className="flex flex-wrap gap-2">
                    {destinations
                        .filter((destination: ExternalDataDestinationApi) =>
                            draftDestinationIds.includes(destination.id)
                        )
                        .map((destination: ExternalDataDestinationApi) => (
                            <LemonTag key={destination.id}>{destination.name}</LemonTag>
                        ))}
                </div>
                <LemonButton type="secondary" onClick={startOverriding}>
                    Choose destinations for this table
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-4">
            <p>This table syncs to the destinations selected here, whatever its source is set to.</p>

            <div className="deprecated-space-y-2">
                {destinations.map((destination: ExternalDataDestinationApi) => (
                    <LemonCheckbox
                        key={destination.id}
                        checked={draftDestinationIds.includes(destination.id)}
                        onChange={() => toggleDestination(destination.id)}
                        label={
                            <span className="flex items-center gap-2">
                                {destination.name}
                                <LemonTag type={destination.is_posthog_warehouse ? 'highlight' : 'default'}>
                                    {destination.type}
                                </LemonTag>
                            </span>
                        }
                    />
                ))}
            </div>

            {draftDestinationIds.length === 0 && (
                <LemonBanner type="warning">
                    Pick at least one destination. To stop syncing this table, turn off syncing instead.
                </LemonBanner>
            )}

            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    onClick={save}
                    loading={overrideLoading}
                    disabledReason={canSave ? undefined : 'Pick at least one destination'}
                >
                    Save
                </LemonButton>
                <LemonButton type="secondary" onClick={clearOverride} loading={overrideLoading}>
                    Follow the source instead
                </LemonButton>
            </div>
        </div>
    )
}
