import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DESTINATION_STATUS_TAGS } from '../../shared/components/destinationStatus'
import { destinationTarget } from '../../shared/components/destinationTarget'
import { DestinationDeliveryFailuresTable } from './DestinationDeliveryFailuresTable'
import { SyncedSources } from './SyncedSources'
import { warehouseDestinationDetailLogic } from './warehouseDestinationDetailLogic'

export interface WarehouseDestinationDetailProps {
    destinationId: string
    /** Null while the destination list loads, or when no destination has this id. */
    destination: ExternalDataDestinationApi | null
    loading: boolean
    onEdit: (destination: ExternalDataDestinationApi) => void
}

const BACK_TO = { key: 'warehouse-destinations', name: 'Warehouse destinations', path: urls.warehouseDestinations() }

export function WarehouseDestinationDetail({
    destinationId,
    destination,
    loading,
    onEdit,
}: WarehouseDestinationDetailProps): JSX.Element {
    const logic = warehouseDestinationDetailLogic({ destinationId })
    const { failures, failuresLoading, failuresError } = useValues(logic)
    const { loadFailures } = useActions(logic)

    if (!destination) {
        return loading ? (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-40" />
            </div>
        ) : (
            <NotFound object="destination" caption="This destination was deleted, or you do not have access to it." />
        )
    }

    const statusTag = DESTINATION_STATUS_TAGS[destination.status]

    return (
        <>
            <SceneTitleSection
                name={destination.name}
                description={destinationTarget(destination) || null}
                resourceType={{ type: 'data_warehouse' }}
                forceBackTo={BACK_TO}
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPencil />}
                        onClick={() => onEdit(destination)}
                        disabledReason={
                            destination.is_posthog_warehouse ? 'The PostHog warehouse is managed for you' : undefined
                        }
                        data-attr="warehouse-destination-detail-edit"
                    >
                        Edit settings
                    </LemonButton>
                }
            />

            {!destination.is_posthog_warehouse && (
                <div className="flex flex-wrap items-center gap-2">
                    <LemonTag type={statusTag.type}>{statusTag.label}</LemonTag>
                    {destination.status !== 'healthy' && destination.latest_error_at ? (
                        <span className="text-muted text-sm">
                            Last failed <TZLabel time={destination.latest_error_at} />
                        </span>
                    ) : null}
                </div>
            )}

            {destination.status === 'paused' && (
                <LemonBanner type="error">
                    <div className="flex flex-col gap-1 min-w-0 break-words">
                        <span>PostHog paused this destination after repeated errors with its settings.</span>
                        {destination.latest_error ? <span>{destination.latest_error}</span> : null}
                        <span>Edit the settings and save them to resume syncing.</span>
                    </div>
                </LemonBanner>
            )}

            <SceneSection
                title="Failed deliveries"
                description="Sync runs that could not write to this destination. Expand a run to see its logs."
            >
                {failuresError ? (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Try again',
                            onClick: loadFailures,
                            loading: failuresLoading,
                            'data-attr': 'warehouse-destination-failures-retry',
                        }}
                    >
                        {failuresError}
                    </LemonBanner>
                ) : (
                    <DestinationDeliveryFailuresTable
                        failures={failures?.results ?? []}
                        loading={failuresLoading || failures === null}
                        windowDays={failures?.window_days ?? null}
                    />
                )}
            </SceneSection>

            <SceneSection title="Synced by">
                <SyncedSources destination={destination} />
            </SceneSection>
        </>
    )
}
