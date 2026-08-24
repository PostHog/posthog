import { useValues } from 'kea'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import {
    RelativeDayRangeNotice,
    isAffectedByRelativeDayRangeChange,
} from '~/queries/nodes/InsightViz/RelativeDayRangeNotice'
import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'

export function RelativeDayRangeDashboardNotice(): JSX.Element | null {
    const { insightTiles } = useValues(dashboardLogic)

    const affectedSource = insightTiles
        .map((tile): InsightQueryNode | null => {
            const query = tile.insight?.query
            const source = query?.kind === NodeKind.InsightVizNode ? (query as InsightVizNode).source : query
            return isInsightQueryNode(source) && isAffectedByRelativeDayRangeChange(source) ? source : null
        })
        .find((source): source is InsightQueryNode => source !== null)

    return affectedSource ? <RelativeDayRangeNotice source={affectedSource} /> : null
}
