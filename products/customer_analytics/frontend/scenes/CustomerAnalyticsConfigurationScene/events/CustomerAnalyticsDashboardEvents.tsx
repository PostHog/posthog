import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonLabel, Link } from '@posthog/lemon-ui'
import { Button, Heading, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
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

    const todayRailNav = useQuillSurface()

    const shouldShowAIButton = !series?.[0] || isPageviewWithoutFilters(series[0])

    const handleSeriesChange = (nextSeries: SeriesNode[]): void => {
        setSeries(nextSeries)
        reportCustomerAnalyticsDashboardEventPickerClicked({ event: title })
    }

    const handleSelectDefault = (): void => {
        setSeries([{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }])
        reportCustomerAnalyticsDashboardEventPickerClicked({ event: title })
    }

    const seriesActionFilter = series ? (
        <SeriesActionFilter
            hideRename
            hideDuplicate
            hideFilter={false}
            propertyFiltersPopover
            series={series}
            onChange={handleSeriesChange}
            insightType={InsightType.TRENDS}
            trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
            typeKey={`customer-analytics-${title.toLowerCase()}`}
            mathAvailability={MathAvailability.None}
            actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            buttonCopy="Select event or action"
            entitiesLimit={1}
            disabled={!!restrictedReason}
        />
    ) : null

    if (todayRailNav) {
        return (
            <div className={`flex flex-col gap-2 py-2 ${highlight}`}>
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            {title}
                        </Heading>
                        {shouldShowAIButton && (
                            <ConfigureWithAIButton event={title} prompt={prompt} disabledReason={restrictedReason} />
                        )}
                    </div>
                    {caption && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {caption}
                        </Text>
                    )}
                </div>
                <div className="flex">
                    {seriesActionFilter ?? (
                        <Button onClick={handleSelectDefault} disabledReason={restrictedReason}>
                            <IconPlus />
                            Select event or action
                        </Button>
                    )}
                </div>
            </div>
        )
    }

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
                <div className="flex">{seriesActionFilter}</div>
            ) : (
                <div className="flex">
                    <LemonButton
                        type="tertiary"
                        icon={<IconPlusSmall />}
                        onClick={handleSelectDefault}
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
    const todayRailNav = useQuillSurface()

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

    const actionDisabledReason = hasChanges ? restrictedReason : 'No changes'

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <Text size="xs" render={<p className="m-0" />}>
                    Need to combine multiple events into one definition?{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.createAction()} target="_blank" />}
                    >
                        Create an action
                    </Button>{' '}
                    first, then select it here.
                </Text>
                {featureFlags[FEATURE_FLAGS.SCHEMA_MANAGEMENT] && (
                    <Text size="xs" render={<p className="m-0" />}>
                        Don't have events yet? You can{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.eventDefinitions()} target="_blank" />}
                        >
                            create event definitions
                        </Button>{' '}
                        upfront and configure your dashboard now.
                        <br />
                        Metrics will populate once you start capturing events.
                    </Text>
                )}

                <div className="flex flex-col gap-2">
                    {eventSelectors.map((eventSelector, index) => (
                        <EventSelector key={index} {...eventSelector} />
                    ))}
                </div>

                <div className="flex flex-wrap gap-2 pt-4">
                    <Button variant="outline" onClick={handleClear} disabledReason={actionDisabledReason}>
                        Clear changes
                    </Button>
                    <Button
                        data-attr="save-customer-analytics-dashboard-events"
                        variant="primary"
                        onClick={handleSave}
                        disabledReason={actionDisabledReason}
                    >
                        Save events
                    </Button>
                </div>
            </div>
        )
    }

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
                <LemonButton type="secondary" onClick={handleClear} disabledReason={actionDisabledReason}>
                    Clear changes
                </LemonButton>
                <LemonButton
                    data-attr="save-customer-analytics-dashboard-events"
                    type="primary"
                    onClick={handleSave}
                    disabledReason={actionDisabledReason}
                >
                    Save events
                </LemonButton>
            </div>
        </div>
    )
}
