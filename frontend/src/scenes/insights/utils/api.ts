import api from 'lib/api'

import { getInsightFilterOrQueryForPersistance } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, QueryBasedInsightModel } from '~/types'

type InsightsApiOptions<Flag> = {
    writeAsQuery: boolean
    readAsQuery: Flag
}

type ReturnedInsightModelByFlag<Flag extends boolean> = Flag extends true ? QueryBasedInsightModel : InsightModel

function getInsightModel<Flag extends boolean>(
    insight: QueryBasedInsightModel,
    asQuery: Flag
): ReturnedInsightModelByFlag<Flag> {
    return {
        ...insight,
        ...getInsightFilterOrQueryForPersistance(insight, asQuery),
    } as ReturnedInsightModelByFlag<Flag>
}

export const insightsApi = {
    async _perform<Flag extends boolean>(
        method: 'create' | 'update',
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        const { writeAsQuery, readAsQuery } = options

        const data = getInsightModel(insight, writeAsQuery)
        const legacyInsight = await api.insights[method](data)

        const response = readAsQuery ? getQueryBasedInsightModel(legacyInsight) : legacyInsight
        return response as ReturnedInsightModelByFlag<Flag>
    },
    async create<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this._perform('create', insight, options)
    },
    async update<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this._perform('update', insight, options)
    },
    async duplicate<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this.create({ ...insight, name: insight.name ? `${insight.name} (copy)` : insight.name }, options)
    },
}
