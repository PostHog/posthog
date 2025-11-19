import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { urls } from 'scenes/urls'

import { eventConfigModalLogic } from 'products/customer_analytics/frontend/components/Insights/eventConfigModalLogic'

export function EventConfigModal(): JSX.Element {
    const { activityEventFilters, hasActivityEventChanged, isOpen } = useValues(eventConfigModalLogic)
    const { saveActivityEvent, setActivityEventSelection, toggleModalOpen } = useActions(eventConfigModalLogic)

    const handleSave = (): void => {
        saveActivityEvent()
        toggleModalOpen(false)
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={toggleModalOpen}
            title="Configure activity event"
            width={800}
            hasUnsavedInput={hasActivityEventChanged}
        >
            <LemonModal.Header>
                <p className="mb-2">
                    Select which event or action defines user activity for your customer analytics dashboard.
                </p>
                <div className="flex items-center gap-1 text-muted text-xs">
                    <IconInfo className="text-base" />
                    <span>
                        To track multiple events as activity, you can{' '}
                        <Link to={urls.createAction()} target="_blank">
                            create an action
                        </Link>{' '}
                        that combines them.
                    </span>
                </div>
            </LemonModal.Header>
            <LemonModal.Content>
                <ActionFilter
                    filters={activityEventFilters}
                    setFilters={setActivityEventSelection}
                    typeKey="customer-analytics-event-config-modal"
                    mathAvailability={MathAvailability.None}
                    hideRename={true}
                    hideDuplicate={false}
                    hideFilter={true}
                    propertyFiltersPopover={true}
                    actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                    buttonCopy="Select event or action"
                    entitiesLimit={1}
                />
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={() => toggleModalOpen()}>
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
