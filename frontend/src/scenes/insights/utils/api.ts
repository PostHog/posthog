import api, { ApiMethodOptions } from 'lib/api'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, HogQLVariable, RefreshType, TileFilters } from '~/queries/schema/schema-general'
import { InsightShortId, InsightModel } from '~/types'

async function _perform(
    method: 'create' | 'update',
    insight: Partial<InsightModel>,
    id?: number,
    options?: ApiMethodOptions
): Promise<InsightModel> {
    const legacyInsight =
        method === 'create' ? await api.insights[method](insight) : await api.insights[method](id!, insight, options)
    return getQueryBasedInsightModel(legacyInsight)
}

export const insightsApi = {
    _perform,
    async getByShortId(
        shortId: InsightShortId,
        basic?: boolean,
        refresh?: RefreshType,
        filtersOverride?: DashboardFilter | null,
        variablesOverride?: Record<string, HogQLVariable> | null,
        tileFiltersOverride?: TileFilters | null
    ): Promise<InsightModel | null> {
        const legacyInsights = await api.insights.loadInsight(
            shortId,
            basic,
            refresh,
            filtersOverride,
            variablesOverride,
            tileFiltersOverride
        )
        if (legacyInsights.results.length === 0) {
            return null
        }
        const legacyInsight = legacyInsights.results[0]
        return getQueryBasedInsightModel(legacyInsight) as InsightModel
    },
    async getByNumericId(numericId: number): Promise<InsightModel | null> {
        const legacyInsight = await api.insights.get(numericId)
        if (legacyInsight === null) {
            return null
        }
        return getQueryBasedInsightModel(legacyInsight)
    },
    async create(insight: Partial<InsightModel>): Promise<InsightModel> {
        return this._perform('create', insight)
    },
    async update(id: number, insightUpdate: Partial<InsightModel>, options?: ApiMethodOptions): Promise<InsightModel> {
        return this._perform('update', insightUpdate, id, options)
    },
    async duplicate(insight: InsightModel): Promise<InsightModel> {
        const { id, short_id, result, created_at, created_by, last_modified_at, last_modified_by, ...rest } = insight
        return this.create({ ...rest, name: insight.name ? `${insight.name} (copy)` : insight.name })
    },
}
