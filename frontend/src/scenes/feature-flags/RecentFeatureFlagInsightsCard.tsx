import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { InsightRow } from 'scenes/project-homepage/RecentInsights'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

import { featureFlagBreakdownInsightUrl } from 'products/feature_flags/frontend/featureFlagKeyLinks'

import { featureFlagLogic } from './featureFlagLogic'

export function RecentFeatureFlagInsights(): JSX.Element {
    const { relatedInsights, relatedInsightsLoading, featureFlag } = useValues(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    return (
        <CompactList
            loading={relatedInsightsLoading}
            emptyMessage={{
                title: 'No insights use this flag yet',
                description: "Create an insight with this flag's breakdown to see it here.",
                buttonText: 'Create insight',
                buttonTo: featureFlagBreakdownInsightUrl(featureFlag.key),
                buttonOnClick: () => {
                    addProductIntentForCrossSell({
                        from: ProductKey.FEATURE_FLAGS,
                        to: ProductKey.PRODUCT_ANALYTICS,
                        intent_context: ProductIntentContext.FEATURE_FLAG_CREATE_INSIGHT,
                    })
                },
            }}
            items={relatedInsights.slice(0, 5)}
            renderRow={(insight: InsightModel, index) => (
                <InsightRow key={index} insight={insight} dataAttr="recent-feature-flag-insight-item" allowWrap />
            )}
            contentHeightBehavior="shrink"
        />
    )
}
