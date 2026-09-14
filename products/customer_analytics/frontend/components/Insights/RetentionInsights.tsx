import { useValues } from 'kea'

import { CustomerAnalyticsQueryCard } from 'products/customer_analytics/frontend/components/CustomerAnalyticsQueryCard'
import { customerAnalyticsSceneLogic } from 'products/customer_analytics/frontend/customerAnalyticsSceneLogic'

export function RetentionInsights(): JSX.Element {
    const { retentionInsights } = useValues(customerAnalyticsSceneLogic)

    return (
        <div className="@container space-y-2">
            <h2 className="ml-1">Retention</h2>
            <div className="grid grid-cols-1 @3xl:grid-cols-2 gap-2">
                {retentionInsights.map((insight, index) => (
                    <CustomerAnalyticsQueryCard key={index} insight={insight} />
                ))}
            </div>
        </div>
    )
}
