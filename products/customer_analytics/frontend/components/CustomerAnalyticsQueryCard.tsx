import { LemonBanner, LemonCard } from '@posthog/lemon-ui'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'

import { customerAnalyticsSceneLogic } from 'products/customer_analytics/frontend/customerAnalyticsSceneLogic'

import { InsightDefinition } from '../insightDefinitions'

interface CustomerAnalyticsQueryCardProps {
    insight: InsightDefinition
    tabId?: string
}

export function CustomerAnalyticsQueryCard({ insight, tabId }: CustomerAnalyticsQueryCardProps): JSX.Element {
    if (insight?.needsConfig) {
        return (
            <LemonCard hoverEffect={false} className="h-[400px] p-0">
                <CardMeta
                    topHeading={<TopHeading query={insight.query} />}
                    content={<InsightMetaContent title={insight.name} description={insight.description} />}
                />
                <LemonBanner type="warning">This insight requires configuration.</LemonBanner>
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
