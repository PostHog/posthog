import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DestinationList } from 'products/data_warehouse/frontend/shared/components/DestinationList'
import { DestinationModal } from 'products/data_warehouse/frontend/shared/components/DestinationModal'
import { destinationModalLogic } from 'products/data_warehouse/frontend/shared/logics/destinationModalLogic'

import { destinationsLogic } from './destinationsLogic'

export interface DestinationsTabProps {
    id: string
}

export function DestinationsTab({ id }: DestinationsTabProps): JSX.Element {
    const logic = destinationsLogic({ sourceId: id })
    const { destinations, destinationsLoading, attachedDestinationIds, savedDestinationIdsLoading, canSave } =
        useValues(logic)
    const { toggleDestination, save, loadDestinations, setAttached } = useActions(logic)

    const modalProps = {
        modalKey: `source-${id}`,
        // A destination you just added is one you meant to use, so select it and let the same Save
        // (and its resync confirmation) apply.
        onSaved: (destination: { id: string }) => {
            loadDestinations()
            if (!attachedDestinationIds.includes(destination.id)) {
                setAttached([...attachedDestinationIds, destination.id])
            }
        },
    }
    const { openForCreate, openForEdit } = useActions(destinationModalLogic(modalProps))

    return (
        <div className="deprecated-space-y-4">
            <div className="flex gap-2 items-start justify-between">
                <p className="max-w-prose">
                    Every table on this source syncs to the destinations turned on here. A table with its own
                    destinations ignores this list.
                </p>
                <LemonButton
                    type="secondary"
                    icon={<IconPlusSmall />}
                    onClick={openForCreate}
                    data-attr="warehouse-destination-new"
                >
                    New destination
                </LemonButton>
            </div>

            <DestinationList
                destinations={destinations}
                loading={destinationsLoading}
                selectedIds={attachedDestinationIds}
                onToggle={toggleDestination}
                onEdit={openForEdit}
            />

            <LemonButton
                type="primary"
                onClick={save}
                loading={savedDestinationIdsLoading}
                disabledReason={canSave ? undefined : 'No changes to save'}
                data-attr="warehouse-destinations-save"
            >
                Save destinations
            </LemonButton>

            <DestinationModal {...modalProps} />
        </div>
    )
}
