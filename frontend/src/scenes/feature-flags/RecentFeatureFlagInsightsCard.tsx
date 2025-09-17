import { useActions, useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { InsightRow } from 'scenes/project-homepage/RecentInsights'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ProductKey, QueryBasedInsightModel } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'

export function RecentFeatureFlagInsights(): JSX.Element {
    const { relatedInsights, relatedInsightsLoading, featureFlag } = useValues(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                { event: '$pageview', name: '$pageview', kind: NodeKind.EventsNode, math: BaseMathType.UniqueUsers },
            ],
            breakdownFilter: {
                breakdown_type: 'event',
                breakdown: `$feature/${featureFlag.key}`,
            },
        },
    }
    return (
        <div className="max-w-prose">
            <CompactList
                loading={relatedInsightsLoading}
                emptyMessage={{
                    title: 'You have no insights that use this feature flag',
                    description: "Explore this feature flag's insights by creating one below.",
                    buttonText: 'Create insight',
                    buttonTo: urls.insightNew({ query }),
                    buttonOnClick: () => {
                        addProductIntentForCrossSell({
                            from: ProductKey.FEATURE_FLAGS,
                            to: ProductKey.PRODUCT_ANALYTICS,
                            intent_context: ProductIntentContext.FEATURE_FLAG_CREATE_INSIGHT,
                        })
                    },
                }}
                items={relatedInsights.slice(0, 5)}
                renderRow={(insight: QueryBasedInsightModel, index) => <InsightRow key={index} insight={insight} />}
                contentHeightBehavior="shrink"
            />
        </div>
    )
}
