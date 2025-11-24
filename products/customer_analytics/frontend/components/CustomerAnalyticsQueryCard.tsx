import { useActions } from 'kea'

import { LemonBanner, LemonButton, LemonCard } from '@posthog/lemon-ui'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'

import {
    InsightDefinition,
    customerAnalyticsSceneLogic,
} from 'products/customer_analytics/frontend/customerAnalyticsSceneLogic'

import { SERIES_TO_EVENT_NAME_MAPPING } from '../constants'
import { eventConfigModalLogic } from './Insights/eventConfigModalLogic'

interface CustomerAnalyticsQueryCardProps {
    insight: InsightDefinition
    tabId?: string
}

function anyValueIsNull(object: object): boolean {
    return Object.values(object).some((value) => value === null)
}

function getEmptySeriesNames(requiredSeries: object): string[] {
    return Object.entries(requiredSeries)
        .filter(([, value]) => !value)
        .map(([key]) => key)
}

export function CustomerAnalyticsQueryCard({ insight, tabId }: CustomerAnalyticsQueryCardProps): JSX.Element {
    const { addEventToHighlight, toggleModalOpen } = useActions(eventConfigModalLogic)
    const needsConfig = insight?.requiredSeries ? anyValueIsNull(insight.requiredSeries) : false

    if (needsConfig) {
        const missingSeries = insight?.requiredSeries ? getEmptySeriesNames(insight.requiredSeries) : []

        const handleClick = (): void => {
            missingSeries.forEach((seriesName) => {
                addEventToHighlight(SERIES_TO_EVENT_NAME_MAPPING[seriesName])
            })
            toggleModalOpen()
        }

        return (
            <LemonCard hoverEffect={false} className="h-[400px] p-0">
                <CardMeta
                    topHeading={<TopHeading query={insight.query} />}
                    content={<InsightMetaContent title={insight.name} description={insight.description} />}
                />

                <LemonBanner type="warning">
                    This insight requires configuration.
                    <div className="flex flex-row items-center gap-4 mt-2 max-w-160">
                        <LemonButton type="primary" onClick={handleClick}>
                            Configure events
                        </LemonButton>
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
            context={{ refresh: 'force_blocking' }}
            className={insight?.className || ''}
            attachTo={customerAnalyticsSceneLogic}
        />
    )
}
