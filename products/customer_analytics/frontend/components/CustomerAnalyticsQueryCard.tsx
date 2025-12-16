import { useValues } from 'kea'

import { LemonBanner, LemonCard } from '@posthog/lemon-ui'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { SurveyOpportunityButtonWithQuery } from 'scenes/surveys/components/SurveyOpportunityButton'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'
import { isValidFunnelQuery } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { AnyEntityNode, ProductKey, QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import {
    InsightDefinition,
    customerAnalyticsSceneLogic,
} from 'products/customer_analytics/frontend/customerAnalyticsSceneLogic'

import { CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../constants'
import { EventSelectorProps } from '../scenes/CustomerAnalyticsConfigurationScene/events/CustomerAnalyticsDashboardEvents'
import { customerAnalyticsDashboardEventsLogic } from '../scenes/CustomerAnalyticsConfigurationScene/events/customerAnalyticsDashboardEventsLogic'
import { buildDashboardItemId } from '../utils'
import { ConfigureWithAIButton } from './ConfigureWithAIButton'

interface CustomerAnalyticsQueryCardProps {
    insight: InsightDefinition
    tabId?: string
}

function anyValueIsNull(object: object): boolean {
    return Object.values(object).some((value) => value === null)
}

function getEmptySeriesNames(requiredSeries: Record<string, AnyEntityNode | null> | undefined): string[] {
    return Object.entries(requiredSeries || {})
        .filter(([, value]) => !value)
        .map(([key]) => key)
}

function generateUniqueKey(name: string, tabId: string, businessType: string, groupType?: number): string {
    const suffix = businessType === 'b2b' ? groupType : 'users'
    return `${name}-${tabId}-${businessType}-${suffix}`
}

export function CustomerAnalyticsQueryCard({ insight, tabId }: CustomerAnalyticsQueryCardProps): JSX.Element {
    const { businessType, selectedGroupType } = useValues(customerAnalyticsSceneLogic)
    const { eventSelectors } = useValues(customerAnalyticsDashboardEventsLogic)
    const needsConfig = insight?.requiredSeries ? anyValueIsNull(insight.requiredSeries) : false
    const uniqueKey = generateUniqueKey(insight.name, tabId || '', businessType, selectedGroupType)
    const insightProps: InsightLogicProps<QuerySchema> = {
        dataNodeCollectionId: CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID,
        dashboardItemId: buildDashboardItemId(uniqueKey),
        query: insight.query,
    }

    // isValidFunnelQuery does not check "business logic" such as conversion
    // rate threshold, etc -- it only checks if the funnel can be targeted
    // by a survey.
    const surveyOpportunityButton = isValidFunnelQuery(insight.query) ? (
        <SurveyOpportunityButtonWithQuery
            insight={insight}
            insightProps={insightProps}
            source={SURVEY_CREATED_SOURCE.CUSTOMER_ANALYTICS_INSIGHT}
            fromProduct={ProductKey.CUSTOMER_ANALYTICS}
        />
    ) : null

    if (needsConfig) {
        const eventsToConfigure = getEmptySeriesNames(insight.requiredSeries)
            .map((seriesName) =>
                eventSelectors.find((selector: EventSelectorProps) => selector.relatedSeries.includes(seriesName))
            )
            .filter((event): event is EventSelectorProps => event !== undefined)

        return (
            <LemonCard hoverEffect={false} className="h-[400px] p-0">
                <CardMeta
                    topHeading={<TopHeading query={insight.query} />}
                    content={<InsightMetaContent title={insight.name} description={insight.description} />}
                />

                <LemonBanner type="warning">
                    <div className="flex flex-row items-center gap-2">This insight requires configuration</div>
                    <div className="flex flex-col items-start gap-2 mt-2 max-w-160">
                        {eventsToConfigure.map((event) => (
                            <ConfigureWithAIButton
                                data-attr={`customer-analytics-configure-${event.title.toLowerCase().replaceAll(' ', '-')}-with-ai`}
                                to={urls.customerAnalyticsConfiguration()}
                                type="primary"
                                eventToHighlight={event.title}
                                prompt={event.prompt}
                                className="border-0"
                            >
                                Configure {event.title.toLowerCase()}
                            </ConfigureWithAIButton>
                        ))}
                    </div>
                </LemonBanner>
            </LemonCard>
        )
    }

    return (
        <QueryCard
            uniqueKey={`${insight.name}-${tabId}`}
            title={insight.name}
            description={insight.description}
            query={insight.query}
            context={{ refresh: 'force_blocking', insightProps }}
            className={insight?.className || ''}
            attachTo={customerAnalyticsSceneLogic}
            extraControls={surveyOpportunityButton}
        />
    )
}
