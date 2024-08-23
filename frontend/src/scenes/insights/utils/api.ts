import api from 'lib/api'

import { getInsightFilterOrQueryForPersistance } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { RefreshType } from '~/queries/schema'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

export type InsightsApiOptions = {
    writeAsQuery: boolean
}

export function getInsightModel<Flag extends boolean>(
    insight: QueryBasedInsightModel,
    asQuery: Flag
): QueryBasedInsightModel {
    return {
        ...insight,
        ...getInsightFilterOrQueryForPersistance(insight, asQuery),
    } as QueryBasedInsightModel
}

async function _perform(
    method: 'create' | 'update',
    insight: Partial<QueryBasedInsightModel>,
    options: InsightsApiOptions,
    id?: number
): Promise<QueryBasedInsightModel> {
    const { writeAsQuery } = options

    const data = getInsightModel(insight as QueryBasedInsightModel, writeAsQuery)
    const legacyInsight = method === 'create' ? await api.insights[method](data) : await api.insights[method](id!, data)

    return getQueryBasedInsightModel(legacyInsight)
}

export const insightsApi = {
    _perform,
    async getByShortId(
        shortId: InsightShortId,
        basic?: boolean,
        refresh?: RefreshType
    ): Promise<QueryBasedInsightModel | null> {
        const legacyInsights = await api.insights.loadInsight(shortId, basic, refresh)
        if (legacyInsights.results.length === 0) {
            return null
        }
        const legacyInsight = legacyInsights.results[0]
        return getQueryBasedInsightModel(legacyInsight) as QueryBasedInsightModel
    },
    async getByNumericId(numericId: number): Promise<QueryBasedInsightModel | null> {
        const legacyInsight = await api.insights.get(numericId)
        if (legacyInsight === null) {
            return null
        }
        return getQueryBasedInsightModel(legacyInsight)
    },
    async create(
        insight: Partial<QueryBasedInsightModel>,
        options: InsightsApiOptions
    ): Promise<QueryBasedInsightModel> {
        return this._perform('create', insight, options)
    },
    async update(
        id: number,
        insightUpdate: Partial<QueryBasedInsightModel>,
        options: InsightsApiOptions
    ): Promise<QueryBasedInsightModel> {
        return this._perform('update', insightUpdate, options, id)
    },
    async duplicate(insight: QueryBasedInsightModel, options: InsightsApiOptions): Promise<QueryBasedInsightModel> {
        return this.create({ ...insight, name: insight.name ? `${insight.name} (copy)` : insight.name }, options)
    },
}
