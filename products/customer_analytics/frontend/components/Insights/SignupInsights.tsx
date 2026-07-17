import { useValues } from 'kea'

import { CustomerAnalyticsQueryCard } from 'products/customer_analytics/frontend/components/CustomerAnalyticsQueryCard'
import {
    InsightDefinition,
    customerAnalyticsSceneLogic,
} from 'products/customer_analytics/frontend/customerAnalyticsSceneLogic'

export function SignupInsights(): JSX.Element {
    const { signupInsights, tabId } = useValues(customerAnalyticsSceneLogic)

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <h2 className="mb-0 ml-1">Signup insights</h2>
            </div>
            <div className="grid grid-cols-[1fr_1fr_2fr] gap-2">
                {signupInsights.slice(0, 3).map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
            <div className="grid grid-cols-3 gap-2">
                {signupInsights.slice(3, 6).map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
            <div className="grid grid-cols-2 gap-2">
                {signupInsights.slice(6).map((insight, index) => {
                    return (
                        <CustomerAnalyticsQueryCard key={index} insight={insight as InsightDefinition} tabId={tabId} />
                    )
                })}
            </div>
        </div>
    )
}
