import { LemonButton } from '@posthog/lemon-ui'
import type {
    ExperimentFunnelsQueryResponse,
    ExperimentTrendsQueryResponse,
    InsightVizNode,
} from '@posthog/query-frontend/schema/schema-general'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'
import type { InsightQueryNode } from '@posthog/query-frontend/schema/schema-general'

import { IconAreaChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyExploreButton({
    result,
    size = 'small',
}: {
    result: ExperimentTrendsQueryResponse | ExperimentFunnelsQueryResponse | null
    size?: 'xsmall' | 'small' | 'large'
}): JSX.Element {
    if (!result) {
        return <></>
    }

    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: (result.kind === NodeKind.ExperimentTrendsQuery
            ? result.count_query
            : result.funnels_query) as InsightQueryNode,
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size={size}
            type="primary"
            icon={<IconAreaChart />}
            to={urls.insightNew({ query })}
            targetBlank
        >
            Explore as Insight
        </LemonButton>
    )
}
