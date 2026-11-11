import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonLabel, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { ChartDisplayCategory, InsightType } from '~/types'

import { ConfigureWithAIButton } from 'products/customer_analytics/frontend/components/ConfigureWithAIButton'
import { isPageviewWithoutFilters } from 'products/customer_analytics/frontend/utils'

import { customerAnalyticsDashboardEventsLogic } from './customerAnalyticsDashboardEventsLogic'

function reportCustomerAnalyticsDashboardEventPickerClicked({ event }: { event: string }): void {
    posthog.capture('customer analytics dashboard event picker clicked', { event })
}

export interface EventSelectorProps {
    caption?: string
    series: SeriesNode[] | null
    setSeries: (series: SeriesNode[]) => void
    title: string
    prompt: string
    relatedSeries: string[]
}

function EventSelector({ series, setSeries, title, caption, prompt }: EventSelectorProps): JSX.Element {
    const { eventsToHighlight } = useValues(customerAnalyticsDashboardEventsLogic)
    const highlight = eventsToHighlight.includes(title) ? 'border rounded border-dashed border-danger' : ''

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const shouldShowAIButton = !series?.[0] || isPageviewWithoutFilters(series[0])

    return (
        <div className={`py-2 ${highlight}`}>
            <div className="ml-1">
                <div className="flex items-center gap-2">
                    <LemonLabel>{title}</LemonLabel>
                    {shouldShowAIButton && (
                        <ConfigureWithAIButton event={title} prompt={prompt} disabledReason={restrictedReason} />
                    )}
                </div>
                <p className="text-xs text-muted-alt">{caption}</p>
            </div>
            {series ? (
                <div className="flex">
                    <SeriesActionFilter
                        hideRename
                        hideDuplicate
                        hideFilter={false}
                        propertyFiltersPopover
                        series={series}
                        onChange={(nextSeries) => {
                            setSeries(nextSeries)
                            reportCustomerAnalyticsDashboardEventPickerClicked({ event: title })
                        }}
                        insightType={InsightType.TRENDS}
                        trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                        typeKey={`customer-analytics-${title.toLowerCase()}`}
                        mathAvailability={MathAvailability.None}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        buttonCopy="Select event or action"
                        entitiesLimit={1}
                        disabled={!!restrictedReason}
                    />
                </div>
            ) : (
                <div className="flex">
                    <LemonButton
                        type="tertiary"
                        icon={<IconPlusSmall />}
                        onClick={() => {
                            setSeries([{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }])
                            reportCustomerAnalyticsDashboardEventPickerClicked({ event: title })
                        }}
                        disabledReason={restrictedReason}
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
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

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
                <LemonButton
                    type="secondary"
                    onClick={handleClear}
                    disabledReason={hasChanges ? restrictedReason : 'No changes'}
                >
                    Clear changes
                </LemonButton>
                <LemonButton
                    data-attr="save-customer-analytics-dashboard-events"
                    type="primary"
                    onClick={handleSave}
                    disabledReason={hasChanges ? restrictedReason : 'No changes'}
                >
                    Save events
                </LemonButton>
            </div>
        </div>
    )
}
