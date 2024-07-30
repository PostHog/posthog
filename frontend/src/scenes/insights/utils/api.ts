import api from 'lib/api'

import { getInsightFilterOrQueryForPersistance } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, QueryBasedInsightModel } from '~/types'

export type InsightsApiOptions<Flag> = {
    writeAsQuery: boolean
    readAsQuery: Flag
}

export type ReadOnlyInsightsApiOptions<Flag> = {
    readAsQuery: Flag
}

type ReturnedInsightModelByFlag<Flag extends boolean> = Flag extends true ? QueryBasedInsightModel : InsightModel

export function getInsightModel<Flag extends boolean>(
    insight: QueryBasedInsightModel,
    asQuery: Flag
): ReturnedInsightModelByFlag<Flag> {
    return {
        ...insight,
        ...getInsightFilterOrQueryForPersistance(insight, asQuery),
    } as ReturnedInsightModelByFlag<Flag>
}

async function _perform<Flag extends boolean>(
    method: 'create' | 'update',
    insight: Partial<QueryBasedInsightModel>,
    options: InsightsApiOptions<Flag>,
    id?: number
): Promise<ReturnedInsightModelByFlag<Flag>> {
    const { writeAsQuery, readAsQuery } = options

    const data = getInsightModel(insight as QueryBasedInsightModel, writeAsQuery)
    const legacyInsight = method === 'create' ? await api.insights[method](data) : await api.insights[method](id!, data)

    const response = readAsQuery ? getQueryBasedInsightModel(legacyInsight) : legacyInsight
    return response as ReturnedInsightModelByFlag<Flag>
}

export const insightsApi = {
    _perform,
    async getByNumericId<Flag extends boolean>(
        numericId: number,
        options: ReadOnlyInsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag> | null> {
        const legacyInsight = await api.insights.get(numericId)
        const response =
            options.readAsQuery && legacyInsight !== null ? getQueryBasedInsightModel(legacyInsight) : legacyInsight
        return response as ReturnedInsightModelByFlag<Flag>
    },
    async create<Flag extends boolean>(
        insight: Partial<QueryBasedInsightModel>,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this._perform('create', insight, options)
    },
    async update<Flag extends boolean>(
        id: number,
        insightUpdate: Partial<QueryBasedInsightModel>,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this._perform('update', insightUpdate, options, id)
    },
    async duplicate<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this.create({ ...insight, name: insight.name ? `${insight.name} (copy)` : insight.name }, options)
    },
}
