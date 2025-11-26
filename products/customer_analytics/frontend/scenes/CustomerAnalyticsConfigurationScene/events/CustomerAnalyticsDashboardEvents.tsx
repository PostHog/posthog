import { useActions, useValues } from 'kea'

import { IconInfo, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonLabel, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { urls } from 'scenes/urls'

import { EntityTypes, FilterType } from '~/types'

import { customerAnalyticsDashboardEventsLogic } from './customerAnalyticsDashboardEventsLogic'

export interface EventSelectorProps {
    caption?: string
    filters: FilterType | null
    setFilters: (filters: FilterType) => void
    title: string
}

function EventSelector({ filters, setFilters, title, caption }: EventSelectorProps): JSX.Element {
    const { eventsToHighlight } = useValues(customerAnalyticsDashboardEventsLogic)
    const highlight = eventsToHighlight.includes(title) ? 'border rounded border-dashed border-danger' : ''

    return (
        <div className={`py-2 ${highlight}`}>
            <div className="ml-1">
                <LemonLabel>{title}</LemonLabel>
                <p className="text-xs text-muted-alt">{caption}</p>
            </div>
            {filters ? (
                <ActionFilter
                    hideRename
                    hideDuplicate
                    hideFilter={false}
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

export function CustomerAnalyticsDashboardEvents(): JSX.Element {
    const { eventSelectors, hasChanges } = useValues(customerAnalyticsDashboardEventsLogic)
    const { saveEvents, clearFilterSelections, clearEventsToHighlight } = useActions(
        customerAnalyticsDashboardEventsLogic
    )

    const handleSave = (): void => {
        saveEvents()
        clearEventsToHighlight()
    }

    const handleClear = (): void => {
        clearFilterSelections()
        clearEventsToHighlight()
    }

    return (
        <div className="space-y-4">
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

            <div className="space-y-2">
                {eventSelectors.map((eventSelector, index) => (
                    <EventSelector key={index} {...eventSelector} />
                ))}
            </div>

            <div className="flex flex-row gap-2 pt-4">
                <LemonButton type="secondary" onClick={handleClear}>
                    Clear changes
                </LemonButton>
                <LemonButton
                    data-attr="save-customer-analytics-dashboard-events"
                    type="primary"
                    onClick={handleSave}
                    disabledReason={hasChanges ? null : 'No changes'}
                >
                    Save events
                </LemonButton>
            </div>
        </div>
    )
}
