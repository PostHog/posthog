import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExpand45, IconOpenSidebar } from '@posthog/icons'
import { LemonMenuItem } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import {
    ProductIntentContext,
    ProductKey,
    QuerySchema,
    TrendsQueryResponse,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'
import { ExporterFormat, InsightLogicProps } from '~/types'

import { TileId, WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import {
    CalendarHeatmapAdapter,
    ExportAdapter,
    TrendsAdapter,
    WebAnalyticsTableAdapter,
    WorldMapAdapter,
    exportTableData,
} from './webAnalyticsExportUtils'
import { webAnalyticsModalLogic } from './webAnalyticsModalLogic'

const NO_ACTIVE_TAB_INSIGHT_PROPS: InsightLogicProps = {
    dashboardItemId: 'web-analytics-no-active-tab-fallback' as const,
    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export function useWebTileExportAdapter(
    query: QuerySchema | undefined,
    insightProps: InsightLogicProps
): ExportAdapter | null {
    const builtInsightDataLogic = insightDataLogic(insightProps)
    const { insightDataRaw } = useValues(builtInsightDataLogic)

    return useMemo(() => {
        if (!insightDataRaw || !query) {
            return null
        }
        const adapters: ExportAdapter[] = [
            new CalendarHeatmapAdapter(insightDataRaw as TrendsQueryResponse, query),
            new WorldMapAdapter(insightDataRaw as TrendsQueryResponse, query),
            new WebAnalyticsTableAdapter(insightDataRaw as WebStatsTableQueryResponse, query),
            new TrendsAdapter(insightDataRaw as TrendsQueryResponse, query),
        ]
        return adapters.find((a) => a.canHandle()) ?? null
    }, [insightDataRaw, query])
}

interface UseWebTileOverflowMenuItemsArgs {
    tileId: TileId
    tabId?: string
    query?: QuerySchema
    insightProps?: InsightLogicProps
    canOpenInsight?: boolean
    canOpenModal?: boolean
    extraMenuItems?: LemonMenuItem[]
}

export function useWebTileOverflowMenuItems({
    tileId,
    tabId,
    query,
    insightProps,
    canOpenInsight,
    canOpenModal,
    extraMenuItems,
}: UseWebTileOverflowMenuItemsArgs): LemonMenuItem[] {
    const effectiveInsightProps = insightProps ?? NO_ACTIVE_TAB_INSIGHT_PROPS
    const { openModal } = useActions(webAnalyticsModalLogic)
    const { getNewInsightUrl } = useValues(webAnalyticsModalLogic)
    const adapter = useWebTileExportAdapter(query, effectiveInsightProps)

    const insightUrl = canOpenInsight ? getNewInsightUrl(tileId, tabId) : undefined

    return useMemo(() => {
        const copyItems: LemonMenuItem[] = [
            {
                label: 'Link',
                onClick: () => {
                    void copyToClipboard(window.location.href, 'link to this view')
                },
            },
            {
                label: 'CSV',
                disabledReason: adapter ? undefined : 'No exportable data yet',
                onClick: () => {
                    if (!adapter) {
                        return
                    }
                    exportTableData(adapter.toTableData(), ExporterFormat.CSV)
                },
            },
            {
                label: 'Query JSON',
                disabledReason: query ? undefined : 'No query loaded yet',
                onClick: () => {
                    if (!query) {
                        return
                    }
                    void copyToClipboard(JSON.stringify(query, null, 2), 'query JSON')
                },
            },
        ]

        const items: LemonMenuItem[] = [
            ...(extraMenuItems ?? []),
            {
                label: 'Copy',
                items: copyItems,
                'data-attr': 'web-analytics-copy-dropdown',
            },
        ]

        if (insightUrl) {
            items.push({
                label: 'Open as new insight',
                icon: <IconOpenSidebar />,
                to: insightUrl,
                onClick: () => {
                    void addProductIntentForCrossSell({
                        from: ProductKey.WEB_ANALYTICS,
                        to: ProductKey.PRODUCT_ANALYTICS,
                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                    })
                },
            })
        }

        if (canOpenModal !== false) {
            items.push({
                label: 'Show more',
                icon: <IconExpand45 />,
                onClick: () => openModal(tileId, tabId),
            })
        }

        return items
    }, [tileId, tabId, query, insightUrl, canOpenModal, openModal, adapter, extraMenuItems])
}
