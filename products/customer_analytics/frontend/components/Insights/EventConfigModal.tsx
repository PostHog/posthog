import { useActions, useValues } from 'kea'

import { IconInfo, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonModal, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { urls } from 'scenes/urls'

import { EntityTypes, FilterType } from '~/types'

import { eventConfigModalLogic } from 'products/customer_analytics/frontend/components/Insights/eventConfigModalLogic'

export function EventConfigModal(): JSX.Element {
    const { eventSelectors, hasChanges, isOpen } = useValues(eventConfigModalLogic)
    const { saveEvents, toggleModalOpen, clearFilterSelections, clearEventsToHighlight } =
        useActions(eventConfigModalLogic)

    const handleSave = (): void => {
        saveEvents()
        toggleModalOpen(false)
        clearEventsToHighlight()
    }

    const onClose = (): void => {
        toggleModalOpen(false)
        clearFilterSelections()
        clearEventsToHighlight()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Configure customer analytics events"
            width={800}
            hasUnsavedInput={hasChanges}
        >
            <LemonModal.Header>
                <p className="mb-2">
                    Configure the events or actions that define different user behaviors for your customer analytics
                    dashboard
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
                <div className="space-y-4">
                    {eventSelectors.map((eventSelector, index) => (
                        <EventSelector key={index} {...eventSelector} />
                    ))}
                </div>
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" onClick={handleSave} disabledReason={hasChanges ? null : 'No changes'}>
                    Save events
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}

export interface EventSelectorProps {
    caption?: string
    filters: FilterType | null
    setFilters: (filters: FilterType) => void
    title: string
}

function EventSelector({ filters, setFilters, title, caption }: EventSelectorProps): JSX.Element {
    const { eventsToHighlight } = useValues(eventConfigModalLogic)
    const highlight = eventsToHighlight.includes(title) ? 'border rounded border-dashed border-danger' : ''

    return (
        <div className={`p-2 ${highlight}`}>
            <div className="ml-1">
                <LemonLabel>{title}</LemonLabel>
                <p className="text-xs text-muted-alt">{caption}</p>
            </div>
            {filters ? (
                <ActionFilter
                    hideRename
                    hideDuplicate
                    hideFilter
                    propertyFiltersPopover
                    filters={filters}
                    setFilters={setFilters}
                    typeKey={`customer-analytics-${title.toLowerCase()}`}
                    mathAvailability={MathAvailability.None}
                    actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                    buttonCopy="Select event or action"
                    entitiesLimit={1}
                />
            ) : (
                <LemonButton
                    type="tertiary"
                    icon={<IconPlusSmall />}
                    onClick={() => {
                        setFilters({
                            events: [
                                {
                                    id: '$pageview',
                                    name: '$pageview',
                                    type: EntityTypes.EVENTS,
                                },
                            ],
                        })
                    }}
                >
                    Select event or action
                </LemonButton>
            )}
        </div>
    )
}
