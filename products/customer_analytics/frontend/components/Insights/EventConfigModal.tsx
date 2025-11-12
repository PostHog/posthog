import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'

export function EventConfigModal(): JSX.Element {
    const { isEventConfigModalOpen, activeEventSelectionWithDefault, hasActiveEventChanged } =
        useValues(customerAnalyticsSceneLogic)
    const { toggleEventConfigModal, setActiveEventSelection, saveActiveEvent } = useActions(customerAnalyticsSceneLogic)

    const handleClose = (): void => {
        toggleEventConfigModal(false)
    }

    const handleSave = (): void => {
        saveActiveEvent()
        toggleEventConfigModal(false)
    }

    return (
        <LemonModal
            isOpen={isEventConfigModalOpen}
            onClose={handleClose}
            title="Configure active event"
            width={600}
            hasUnsavedInput={hasActiveEventChanged}
        >
            <LemonModal.Content>
                <p className="mb-4">Select which event defines user activity for your customer analytics dashboard.</p>
                <ActionFilter
                    filters={activeEventSelectionWithDefault}
                    setFilters={setActiveEventSelection}
                    typeKey="customer-analytics-event-config-modal"
                    mathAvailability={MathAvailability.None}
                    hideDeleteBtn={true}
                    hideRename={true}
                    hideDuplicate={true}
                    hideFilter={true}
                    entitiesLimit={1}
                    actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                />
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={hasActiveEventChanged ? null : 'No changes'}
                >
                    Save active event
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
