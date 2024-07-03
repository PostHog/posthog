import api from 'lib/api'

import { getInsightFilterOrQueryForPersistance } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, QueryBasedInsightModel } from '~/types'

type ReturnedInsightModelByFlag<Flag extends boolean> = Flag extends true ? QueryBasedInsightModel : InsightModel

export const insightsApi = {
    async create<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: {
            writeAsQuery: boolean
            readAsQuery: Flag
        }
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        const data = {
            ...insight,
            ...getInsightFilterOrQueryForPersistance(insight, options.writeAsQuery),
        }
        const legacyInsight: InsightModel = await api.insights.create(data)
        return (
            options.readAsQuery ? getQueryBasedInsightModel(legacyInsight) : legacyInsight
        ) as ReturnedInsightModelByFlag<Flag>
    },
}
