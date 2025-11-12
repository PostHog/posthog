import { LemonBanner, LemonCard } from '@posthog/lemon-ui'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { InsightMetaContent } from 'lib/components/Cards/InsightCard/InsightMeta'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'

import { InsightDefinition } from '../insightDefinitions'

interface CustomerAnalyticsQueryCardProps {
    insight: InsightDefinition
}
export function CustomerAnalyticsQueryCard({ insight }: CustomerAnalyticsQueryCardProps): JSX.Element {
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
            title={insight.name}
            description={insight.description}
            query={insight.query}
            context={{ refresh: 'force_blocking' }}
            className={insight?.className || ''}
        />
    )
}
