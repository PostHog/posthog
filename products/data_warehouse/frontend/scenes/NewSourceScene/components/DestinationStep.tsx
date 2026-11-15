import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { DestinationList } from 'products/data_warehouse/frontend/shared/components/DestinationList'
import { DestinationModal } from 'products/data_warehouse/frontend/shared/components/DestinationModal'
import { destinationModalLogic } from 'products/data_warehouse/frontend/shared/logics/destinationModalLogic'

import { destinationStepLogic } from './destinationStepLogic'

export function DestinationStep(): JSX.Element {
    const { destinations, destinationsLoading, selectedIds, hasLoaded } = useValues(destinationStepLogic)
    const { loadDestinations, toggleDestination, selectDefault } = useActions(destinationStepLogic)

    useEffect(() => {
        // The warehouse is preselected once the list resolves, so a person who ignores this step
        // gets what they would have got before destinations existed.
        if (hasLoaded) {
            selectDefault()
        }
    }, [hasLoaded]) // oxlint-disable-line react-hooks/exhaustive-deps

    const modalProps = {
        modalKey: 'wizard',
        onSaved: (destination: { id: string }) => {
            loadDestinations()
            if (!selectedIds.includes(destination.id)) {
                toggleDestination(destination.id)
            }
        },
        onDeleted: (destinationId: string) => {
            loadDestinations()
            if (selectedIds.includes(destinationId)) {
                toggleDestination(destinationId)
            }
        },
    }
    const { openForCreate, openForEdit } = useActions(destinationModalLogic(modalProps))

    // A team with no destination rows yet has nothing to turn on, and its source writes to the
    // PostHog warehouse, so that case reads as warehouse-only rather than as nowhere to sync.
    const nothingSelected = destinations.length > 0 && selectedIds.length === 0
    const warehouseOnly =
        destinations.length === 0 ||
        !selectedIds.some((id) => destinations.find((d) => d.id === id)?.type !== 'PostHogWarehouse')

    return (
        <div className="deprecated-space-y-4">
            <div className="flex gap-2 items-start justify-between">
                <p className="max-w-prose">
                    Choose where this source writes its tables. Picking them now means the first sync already lands
                    there. Adding one later re-reads every table from the source to fill in the history.
                </p>
                <LemonButton
                    type="secondary"
                    icon={<IconPlusSmall />}
                    onClick={openForCreate}
                    data-attr="wizard-destination-new"
                >
                    New destination
                </LemonButton>
            </div>

            <DestinationList
                destinations={destinations}
                loading={destinationsLoading}
                selectedIds={selectedIds}
                onToggle={toggleDestination}
                onEdit={openForEdit}
            />

            {!destinationsLoading &&
                (nothingSelected ? (
                    <LemonBanner type="warning">
                        This source has nowhere to sync. Turn on at least one destination to import it.
                    </LemonBanner>
                ) : (
                    warehouseOnly && (
                        <LemonBanner type="info">
                            This source will sync into PostHog only. Turn on another destination to also send its tables
                            to your own database.
                        </LemonBanner>
                    )
                ))}

            <DestinationModal {...modalProps} />
        </div>
    )
}
