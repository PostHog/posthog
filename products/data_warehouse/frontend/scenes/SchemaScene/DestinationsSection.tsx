import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { DestinationList } from 'products/data_warehouse/frontend/shared/components/DestinationList'
import { DestinationModal } from 'products/data_warehouse/frontend/shared/components/DestinationModal'
import { destinationModalLogic } from 'products/data_warehouse/frontend/shared/logics/destinationModalLogic'

import { schemaDestinationsLogic } from './schemaDestinationsLogic'

export interface DestinationsSectionProps {
    schemaId: string
}

export function DestinationsSection({ schemaId }: DestinationsSectionProps): JSX.Element {
    const logic = schemaDestinationsLogic({ schemaId })
    const { destinations, destinationsLoading, draftDestinationIds, isOverriding, overrideLoading, canSave } =
        useValues(logic)
    const { toggleDestination, setOverriding, save, clearOverride, loadDestinations } = useActions(logic)

    const modalProps = {
        modalKey: `schema-${schemaId}`,
        onSaved: (destination: { id: string }) => {
            loadDestinations()
            if (isOverriding && !draftDestinationIds.includes(destination.id)) {
                toggleDestination(destination.id)
            }
        },
    }
    const { openForCreate, openForEdit } = useActions(destinationModalLogic(modalProps))

    return (
        <div className="deprecated-space-y-4">
            <div className="flex gap-2 items-start justify-between">
                <LemonSwitch
                    bordered
                    checked={isOverriding}
                    onChange={setOverriding}
                    label="Override source destinations"
                    data-attr="warehouse-schema-destinations-override"
                />
                <LemonButton
                    type="secondary"
                    icon={<IconPlusSmall />}
                    onClick={openForCreate}
                    data-attr="warehouse-destination-new"
                >
                    New destination
                </LemonButton>
            </div>

            {!isOverriding && (
                <LemonBanner type="info">
                    This table syncs to whatever its source is set to. Turn on the override to choose destinations just
                    for this table.
                </LemonBanner>
            )}

            <DestinationList
                destinations={destinations}
                loading={destinationsLoading}
                selectedIds={draftDestinationIds}
                onToggle={toggleDestination}
                onEdit={openForEdit}
                toggleDisabledReason={
                    isOverriding ? undefined : 'This table follows its source. Turn on the override to change it.'
                }
            />

            {isOverriding && (
                <div className="flex gap-2">
                    <LemonButton
                        type="primary"
                        onClick={save}
                        loading={overrideLoading}
                        disabledReason={canSave ? undefined : 'Pick at least one destination'}
                        data-attr="warehouse-schema-destinations-save"
                    >
                        Save
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={clearOverride}
                        loading={overrideLoading}
                        data-attr="warehouse-schema-destinations-reset"
                    >
                        Reset to source destinations
                    </LemonButton>
                </div>
            )}

            <DestinationModal {...modalProps} />
        </div>
    )
}
