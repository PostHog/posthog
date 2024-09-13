import api from 'lib/api'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, RefreshType } from '~/queries/schema'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

async function _perform(
    method: 'create' | 'update',
    insight: Partial<QueryBasedInsightModel>,
    id?: number
): Promise<QueryBasedInsightModel> {
    const legacyInsight =
        method === 'create' ? await api.insights[method](insight) : await api.insights[method](id!, insight)
    return getQueryBasedInsightModel(legacyInsight)
}

export const insightsApi = {
    _perform,
    async getByShortId(
        shortId: InsightShortId,
        basic?: boolean,
        refresh?: RefreshType,
        filtersOverride?: DashboardFilter | null
    ): Promise<QueryBasedInsightModel | null> {
        const legacyInsights = await api.insights.loadInsight(shortId, basic, refresh, filtersOverride)
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
    async create(insight: Partial<QueryBasedInsightModel>): Promise<QueryBasedInsightModel> {
        return this._perform('create', insight)
    },
    async update(id: number, insightUpdate: Partial<QueryBasedInsightModel>): Promise<QueryBasedInsightModel> {
        return this._perform('update', insightUpdate, id)
    },
    async duplicate(insight: QueryBasedInsightModel): Promise<QueryBasedInsightModel> {
        return this.create({ ...insight, name: insight.name ? `${insight.name} (copy)` : insight.name })
    },
}
