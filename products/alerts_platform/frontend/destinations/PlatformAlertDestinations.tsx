import { BindLogic, useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { PlatformAlertCreateDestinationApi, PlatformAlertDestinationApi } from '../generated/api.schemas'
import { PlatformAlertDestinationAddForm } from './PlatformAlertDestinationAddForm'
import { MAX_DESTINATIONS_PER_ALERT, destinationTarget, destinationTypeLabel } from './platformAlertDestinationFormat'
import { PlatformAlertDestinationsLogicProps, platformAlertDestinationsLogic } from './platformAlertDestinationsLogic'

/** An alert's own notification destinations. Before the alert exists, they wait as pending and are added once it is saved. */
export function PlatformAlertDestinations(props: PlatformAlertDestinationsLogicProps): JSX.Element {
    return (
        <BindLogic logic={platformAlertDestinationsLogic} props={props}>
            <DestinationsContent />
        </BindLogic>
    )
}

function DestinationsContent(): JSX.Element {
    const {
        destinations,
        destinationsLoading,
        destinationsLoadFailed,
        pendingDestinations,
        removingDestinationIds,
        isAddingDestination,
        atDestinationLimit,
    } = useValues(platformAlertDestinationsLogic)
    const { loadDestinations, removeDestination, removePendingDestination, startAddingDestination } =
        useActions(platformAlertDestinationsLogic)

    if (destinationsLoading && destinations === null) {
        return <Spinner />
    }
    if (destinationsLoadFailed && destinations === null) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadDestinations() }}>
                Could not load this alert's destinations.
            </LemonBanner>
        )
    }

    const isEmpty = (destinations?.length ?? 0) === 0 && pendingDestinations.length === 0

    return (
        <div className="space-y-2">
            {isEmpty && !isAddingDestination ? (
                <p className="text-sm text-secondary m-0">No destinations yet. Add one to get notified.</p>
            ) : null}
            {destinations?.map((destination) => (
                <DestinationRow
                    key={destination.id}
                    destination={destination}
                    removing={removingDestinationIds.has(destination.id)}
                    onRemove={() => removeDestination(destination.id)}
                />
            ))}
            {pendingDestinations.map((destination, index) => (
                <DestinationRow
                    key={index}
                    destination={destination}
                    onRemove={() => removePendingDestination(index)}
                />
            ))}
            {isAddingDestination ? (
                <PlatformAlertDestinationAddForm />
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={startAddingDestination}
                    disabledReason={
                        atDestinationLimit
                            ? `An alert can have at most ${MAX_DESTINATIONS_PER_ALERT} destinations`
                            : undefined
                    }
                    data-attr="platform-alert-destination-add"
                >
                    Add destination
                </LemonButton>
            )}
        </div>
    )
}

function DestinationRow({
    destination,
    removing = false,
    onRemove,
}: {
    destination: PlatformAlertDestinationApi | PlatformAlertCreateDestinationApi
    removing?: boolean
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-2 border rounded px-2 py-1">
            <LemonTag>{destinationTypeLabel(destination.type)}</LemonTag>
            {/* A pending webhook URL carries its secret path, so it is not captured. */}
            <span className="flex-1 min-w-0 truncate text-sm ph-no-capture">{destinationTarget(destination)}</span>
            <LemonButton
                icon={<IconTrash />}
                size="small"
                tooltip="Remove destination"
                loading={removing}
                onClick={onRemove}
                data-attr="platform-alert-destination-remove"
            />
        </div>
    )
}
