import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { InsightRow } from 'scenes/project-homepage/RecentInsights'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { BaseMathType, QueryBasedInsightModel } from '~/types'

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

    if (relatedInsightsLoading) {
        return (
            <div className="flex flex-col gap-2 py-2">
                {Array.from({ length: 3 }, (_, i) => (
                    <LemonSkeleton key={i} className="h-4" />
                ))}
            </div>
        )
    }

    if (relatedInsights.length === 0) {
        return (
            <div className="flex flex-col items-center gap-2 py-3 text-center">
                <span className="text-xs text-muted">No insights use this flag yet</span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    to={urls.insightNew({ query })}
                    onClick={() => {
                        addProductIntentForCrossSell({
                            from: ProductKey.FEATURE_FLAGS,
                            to: ProductKey.PRODUCT_ANALYTICS,
                            intent_context: ProductIntentContext.FEATURE_FLAG_CREATE_INSIGHT,
                        })
                    }}
                >
                    Create insight
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col">
            {relatedInsights.slice(0, 5).map((insight: QueryBasedInsightModel, index) => (
                <InsightRow key={index} insight={insight} dataAttr="recent-feature-flag-insight-item" allowWrap />
            ))}
        </div>
    )
}
