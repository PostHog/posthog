import api, { PaginatedResponse } from 'lib/api'

import { getInsightFilterOrQueryForPersistance } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, QueryBasedInsightModel } from '~/types'

export type InsightsApiOptions<Flag> = {
    writeAsQuery: boolean
    readAsQuery: Flag
}

export type InsightsApiReadOptions<Flag> = {
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

export const insightsApi = {
    async _perform<Flag extends boolean>(
        method: 'create' | 'update',
        options: InsightsApiOptions<Flag>,
        id?: number,
        insight?: Partial<QueryBasedInsightModel>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        const { writeAsQuery, readAsQuery } = options

        const data =
            'filters' in (insight || {}) ? getInsightModel(insight as QueryBasedInsightModel, writeAsQuery) : insight
        const legacyInsight =
            method === 'create' ? await api.insights[method](data) : await api.insights[method](id!, data)

        const response = readAsQuery ? getQueryBasedInsightModel(legacyInsight) : legacyInsight
        return response as ReturnedInsightModelByFlag<Flag>
    },
    async create<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this._perform('create', options, undefined, insight)
    },
    async get<Flag extends boolean>(
        id: number,
        options: InsightsApiReadOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        const { readAsQuery } = options

        const legacyInsight = await api.insights.get(id)

        const response = readAsQuery ? getQueryBasedInsightModel(legacyInsight) : legacyInsight
        return response as ReturnedInsightModelByFlag<Flag>
    },
    async list<Flag extends boolean>(
        params: Record<string, any>,
        options: InsightsApiReadOptions<Flag>
    ): Promise<PaginatedResponse<ReturnedInsightModelByFlag<Flag>>> {
        const { readAsQuery } = options

        const response = await api.insights.list(params)

        if (readAsQuery) {
            ;(response as PaginatedResponse<QueryBasedInsightModel>).results = response.results.map((legacyInsight) =>
                getQueryBasedInsightModel(legacyInsight)
            )
        }

        return response as PaginatedResponse<ReturnedInsightModelByFlag<Flag>>
    },
    async update<Flag extends boolean>(
        id: number,
        insightUpdate: Partial<QueryBasedInsightModel>,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this._perform('update', options, id, insightUpdate)
    },
    async duplicate<Flag extends boolean>(
        insight: QueryBasedInsightModel,
        options: InsightsApiOptions<Flag>
    ): Promise<ReturnedInsightModelByFlag<Flag>> {
        return this.create({ ...insight, name: insight.name ? `${insight.name} (copy)` : insight.name }, options)
    },
}
