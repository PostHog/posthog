import { BindLogic } from 'kea'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID } from '../aiObservabilitySharedLogic'
import { AIObservabilityMetricChart, AIObservabilityMetricChartProps } from './AIObservabilityMetricChart'

/** A one-line table toolbar with the chart under it, and one reload that refreshes both. */
export function metricChartTableProps(
    uniqueKey: string,
    chart: Omit<AIObservabilityMetricChartProps, 'collectionId'>
): { query: Partial<DataTableNode>; context: QueryContext<DataTableNode> } {
    // Its own collection per tab: the tables stay mounted after a tab switch, so a shared one reloads hidden tabs too.
    const collectionId = `${AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID}-${uniqueKey}`
    return {
        // The timer and reload move into customActions; the staff timings flag would force the built-in timer back.
        query: { showReload: false, showElapsedTime: false, showTimings: false },
        context: {
            compactDataTableToolbar: true,
            // Joining the chart's collection is what lets ReloadAll refresh both.
            insightProps: { dashboardItemId: `new-AdHoc.DataNode.${uniqueKey}`, dataNodeCollectionId: collectionId },
            customActions: [
                <ElapsedTime key="elapsed-time" />,
                <BindLogic key="reload-all" logic={dataNodeCollectionLogic} props={{ key: collectionId }}>
                    <ReloadAll />
                </BindLogic>,
            ],
            dataTableBelowToolbar: <AIObservabilityMetricChart {...chart} collectionId={collectionId} />,
        },
    }
}
