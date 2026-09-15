import { useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { DataNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

export interface MarketingAnalyticsPrecomputeStatus {
    /** The window this read asked for has not been warmed yet. */
    notReady: boolean
    /** ISO timestamp of the oldest precompute window behind the result, or null when nothing was read. */
    computedAt: string | null
}

/** The precompute-only signals a marketing analytics response carries.
 *
 * Marketing analytics serves exclusively from precompute, so a cold window comes back as an empty result
 * with `precomputeNotReady` set — a tile that only looks at the rows cannot tell that apart from a team
 * with no spend. Binds the same dataNodeLogic instance the tile's own DataTable builds, so the query
 * still loads once. */
export function useMarketingAnalyticsPrecompute(
    source: DataNode,
    insightProps: InsightLogicProps
): MarketingAnalyticsPrecomputeStatus {
    const { response, responseLoading } = useValues(
        dataNodeLogic({
            query: source,
            key: insightVizDataNodeKey(insightProps),
            dataNodeCollectionId: insightProps.dataNodeCollectionId,
        })
    )
    const precomputeResponse = response as { precomputeNotReady?: boolean; dataComputedAt?: string } | null

    return {
        notReady: !responseLoading && precomputeResponse?.precomputeNotReady === true,
        computedAt: precomputeResponse?.dataComputedAt ?? null,
    }
}
