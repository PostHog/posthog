import { useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { DataNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

/** Whether a marketing analytics query answered that its precompute window has not been warmed yet.
 *
 * Marketing analytics serves exclusively from precompute, so a cold window comes back as an empty result
 * with `precomputeNotReady` set — a tile that only looks at the rows cannot tell that apart from a team
 * with no spend. Binds the same dataNodeLogic instance the tile's own DataTable builds, so the query
 * still loads once. */
export function useMarketingAnalyticsNotReady(source: DataNode, insightProps: InsightLogicProps): boolean {
    const { response, responseLoading } = useValues(
        dataNodeLogic({
            query: source,
            key: insightVizDataNodeKey(insightProps),
            dataNodeCollectionId: insightProps.dataNodeCollectionId,
        })
    )
    return !responseLoading && (response as { precomputeNotReady?: boolean } | null)?.precomputeNotReady === true
}
