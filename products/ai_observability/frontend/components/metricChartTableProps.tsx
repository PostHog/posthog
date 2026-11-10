import { BindLogic } from 'kea'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID } from '../aiObservabilitySharedLogic'

/** A one-line table toolbar with the chart under it, and one reload that refreshes both. */
export function metricChartTableProps(
    uniqueKey: string,
    chart: JSX.Element
): { query: Partial<DataTableNode>; context: QueryContext<DataTableNode> } {
    return {
        // The timer and reload move into customActions; the staff timings flag would force the built-in timer back.
        query: { showReload: false, showElapsedTime: false, showTimings: false },
        context: {
            compactDataTableToolbar: true,
            // Joining the scene's collection is what lets ReloadAll refresh the chart too.
            insightProps: {
                dashboardItemId: `new-AdHoc.DataNode.${uniqueKey}`,
                dataNodeCollectionId: AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID,
            },
            customActions: [
                <ElapsedTime key="elapsed-time" />,
                <BindLogic
                    key="reload-all"
                    logic={dataNodeCollectionLogic}
                    props={{ key: AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}
                >
                    <ReloadAll />
                </BindLogic>,
            ],
            dataTableBelowToolbar: chart,
        },
    }
}
