import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'

export function EventConfigModal(): JSX.Element {
    const { isEventConfigModalOpen, activityEventFilters, hasActivityEventChanged } =
        useValues(customerAnalyticsSceneLogic)
    const { toggleEventConfigModal, setActivityEventSelection, saveActivityEvent } =
        useActions(customerAnalyticsSceneLogic)

    const handleClose = (): void => {
        toggleEventConfigModal(false)
    }

    const handleSave = (): void => {
        saveActivityEvent()
        toggleEventConfigModal(false)
    }

    return (
        <LemonModal
            isOpen={isEventConfigModalOpen}
            onClose={handleClose}
            title="Configure activity event"
            width={600}
            hasUnsavedInput={hasActivityEventChanged}
        >
            <LemonModal.Content>
                <p className="mb-4">
                    Select which event or action define user activity for your customer analytics dashboard.
                </p>
                <ActionFilter
                    filters={activityEventFilters}
                    setFilters={setActivityEventSelection}
                    typeKey="customer-analytics-event-config-modal"
                    mathAvailability={MathAvailability.None}
                    hideDeleteBtn={true}
                    hideRename={true}
                    hideDuplicate={true}
                    hideFilter={true}
                    entitiesLimit={1}
                    actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                />
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={hasActivityEventChanged ? null : 'No changes'}
                >
                    Save activity event
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
