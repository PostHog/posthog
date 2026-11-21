import { ComponentType } from 'react'

import { IconInsightFunnels, IconInsightRetention, IconInsightTrends } from 'lib/lemon-ui/icons'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import {
    INSIGHT_TYPES_METADATA,
    QUERY_TYPES_METADATA,
    isInsightTypeCreatable,
} from 'scenes/saved-insights/insightTypesMetadata'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

export interface AddInsightCreateOption {
    type: string
    label: string
    icon?: ComponentType<any>
    url: string
    dataAttr: string
    tooltip?: string
}

const QUICK_CREATE_TYPES = [
    { type: InsightType.TRENDS, icon: IconInsightTrends, label: 'Trend' },
    { type: InsightType.FUNNELS, icon: IconInsightFunnels, label: 'Funnel' },
    { type: InsightType.RETENTION, icon: IconInsightRetention, label: 'Retention' },
]

export function addInsightToDashboardCreateOptions({
    dashboardId,
    tileGroupKey,
    featureFlags,
    showMetricsInsight,
}: {
    dashboardId: number | undefined
    tileGroupKey: string | null
    featureFlags: FeatureFlagsSet
    showMetricsInsight: boolean
}): { quickCreate: AddInsightCreateOption[]; moreCreate: AddInsightCreateOption[] } {
    const insightUrl = (type: InsightType): string => urls.insightNew({ type, dashboardId, tileGroupKey })

    const quickCreate = QUICK_CREATE_TYPES.map(({ type, icon, label }) => ({
        type,
        label,
        icon,
        url: insightUrl(type),
        dataAttr: `quick-create-${type.toLowerCase()}`,
        tooltip: INSIGHT_TYPES_METADATA[type]?.description,
    }))

    const moreCreate: AddInsightCreateOption[] = Object.entries(INSIGHT_TYPES_METADATA)
        .filter(
            ([type, meta]) =>
                isInsightTypeCreatable(meta, featureFlags) &&
                type !== InsightType.JSON &&
                type !== InsightType.HOG &&
                !QUICK_CREATE_TYPES.some((qt) => qt.type === type)
        )
        .map(([type, meta]) => ({
            type,
            label: meta.name,
            icon: meta.icon,
            url:
                type === InsightType.SQL
                    ? urls.sqlEditor({ dashboard: dashboardId, tileGroupKey })
                    : insightUrl(type as InsightType),
            dataAttr: `create-${type.toLowerCase()}`,
        }))

    if (showMetricsInsight) {
        moreCreate.push({
            type: InsightType.METRICS,
            label: QUERY_TYPES_METADATA[NodeKind.MetricsQuery].name,
            icon: QUERY_TYPES_METADATA[NodeKind.MetricsQuery].icon,
            url: insightUrl(InsightType.METRICS),
            dataAttr: 'create-metrics',
        })
    }

    return { quickCreate, moreCreate }
}
