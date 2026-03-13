import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonLabel, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { EntityTypes, FilterType } from '~/types'

import { ConfigureWithAIButton } from 'products/customer_analytics/frontend/components/ConfigureWithAIButton'
import { isPageviewWithoutFilters } from 'products/customer_analytics/frontend/utils'

import { customerAnalyticsDashboardEventsLogic } from './customerAnalyticsDashboardEventsLogic'

export interface EventSelectorProps {
    caption?: string
    filters: FilterType | null
    setFilters: (filters: FilterType) => void
    title: string
    prompt: string
    relatedSeries: string[]
}

function EventSelector({ filters, setFilters, title, caption, prompt }: EventSelectorProps): JSX.Element {
    const { eventsToHighlight } = useValues(customerAnalyticsDashboardEventsLogic)
    const highlight = eventsToHighlight.includes(title) ? 'border rounded border-dashed border-danger' : ''
    const { reportCustomerAnalyticsDashboardEventPickerClicked } = useActions(eventUsageLogic)

    const shouldShowAIButton =
        !filters || isPageviewWithoutFilters(actionsAndEventsToSeries(filters as any, true, MathAvailability.None)[0])

    return (
        <div className={`py-2 ${highlight}`}>
            <div className="ml-1">
                <div className="flex items-center gap-2">
                    <LemonLabel>{title}</LemonLabel>
                    {shouldShowAIButton && <ConfigureWithAIButton event={title} prompt={prompt} />}
                </div>
                <p className="text-xs text-muted-alt">{caption}</p>
            </div>
            {filters ? (
                <div className="flex">
                    <ActionFilter
                        hideRename
                        hideDuplicate
                        hideFilter={false}
                        propertyFiltersPopover
                        filters={filters}
                        setFilters={(filters) => {
                            setFilters(filters)
                            reportCustomerAnalyticsDashboardEventPickerClicked({ event: title })
                        }}
                        typeKey={`customer-analytics-${title.toLowerCase()}`}
                        mathAvailability={MathAvailability.None}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        buttonCopy="Select event or action"
                        entitiesLimit={1}
                    />
                </div>
            ) : (
                <div className="flex">
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
                            reportCustomerAnalyticsDashboardEventPickerClicked({ event: title })
                        }}
                    >
                        Select event or action
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function CustomerAnalyticsDashboardEvents(): JSX.Element {
    const { eventSelectors, hasChanges } = useValues(customerAnalyticsDashboardEventsLogic)
    const { saveEvents, clearFilterSelections, clearEventsToHighlight } = useActions(
        customerAnalyticsDashboardEventsLogic
    )
    const { addProductIntent } = useActions(teamLogic)
    const { reportCustomerAnalyticsDashboardConfigurationViewed, reportCustomerAnalyticsDashboardEventsSaved } =
        useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const handleSave = (): void => {
        saveEvents()
        clearEventsToHighlight()
        reportCustomerAnalyticsDashboardEventsSaved()
        addProductIntent({
            product_type: ProductKey.CUSTOMER_ANALYTICS,
            intent_context: ProductIntentContext.CUSTOMER_ANALYTICS_DASHBOARD_EVENTS_SAVED,
        })
    }

    const handleClear = (): void => {
        clearFilterSelections()
        clearEventsToHighlight()
    }

    useOnMountEffect(() => {
        reportCustomerAnalyticsDashboardConfigurationViewed()
    })

    return (
        <div className="space-y-4">
            <p>
                Need to combine multiple events into one definition?{' '}
                <Link to={urls.createAction()} target="_blank">
                    Create an action
                </Link>{' '}
                first, then select it here.
            </p>
            {featureFlags[FEATURE_FLAGS.SCHEMA_MANAGEMENT] && (
                <p>
                    Don't have events yet? You can{' '}
                    <Link to={urls.eventDefinitions()} target="_blank">
                        create event definitions
                    </Link>{' '}
                    upfront and configure your dashboard now.
                    <br />
                    Metrics will populate once you start capturing events.
                </p>
            )}

            <div className="space-y-2">
                {eventSelectors.map((eventSelector, index) => (
                    <EventSelector key={index} {...eventSelector} />
                ))}
            </div>

            <div className="flex flex-row gap-2 pt-4">
                <LemonButton type="secondary" onClick={handleClear} disabledReason={hasChanges ? null : 'No changes'}>
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
