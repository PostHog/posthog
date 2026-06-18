import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExpand45 } from '@posthog/icons'
import { LemonButtonProps, LemonMenuItem } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    ProductIntentContext,
    ProductKey,
    QuerySchema,
    TrendsQueryResponse,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'
import { ExporterFormat, InsightLogicProps } from '~/types'

import { TileId, WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import { shareNudgeLogic } from './shareNudgeLogic'
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
    dashboardItemId: 'new-AdHoc.web-analytics-no-active-tab-fallback',
    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
}

export function useWebTileExportAdapter(
    query: QuerySchema | undefined,
    insightProps: InsightLogicProps
): ExportAdapter | null {
    // This header hook renders before the tile's chart. insightDataLogic (mounted below) connects to
    // the shared, key-only dataNodeLogic without forwarding dataNodeCollectionId, so it would build
    // that logic first and bind it to a fallback collection — dropping the tile from the dashboard's
    // "reload all" (only the overview, which isn't an insight viz, kept reloading). Bind the node to
    // the web analytics collection up front, keyed by the node key so it tracks tab switches, so the
    // chart reuses the same correctly-bound instance and reload reaches every tile.
    const dataNodeKey = insightVizDataNodeKey(insightProps)
    const collectionBoundDataNodeLogic = useMemo(
        () =>
            dataNodeLogic({
                key: dataNodeKey,
                dataNodeCollectionId: insightVizDataCollectionId(insightProps, dataNodeKey),
                loadPriority: insightProps.loadPriority,
            } as DataNodeLogicProps),
        // Rebind only when the node key changes (tile/tab switch); avoid re-running on every render so
        // we never clobber the query the chart sets on the shared instance.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [dataNodeKey]
    )
    useMountedLogic(collectionBoundDataNodeLogic)

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
    canOpenModal?: boolean
    extraMenuItems?: LemonMenuItem[]
}

export function useWebTileOverflowMenuItems({
    tileId,
    tabId,
    query,
    insightProps,
    canOpenModal,
    extraMenuItems,
}: UseWebTileOverflowMenuItemsArgs): LemonMenuItem[] {
    const effectiveInsightProps = insightProps ?? NO_ACTIVE_TAB_INSIGHT_PROPS
    const { openModal } = useActions(webAnalyticsModalLogic)
    const { exportTriggered } = useActions(shareNudgeLogic)
    const adapter = useWebTileExportAdapter(query, effectiveInsightProps)

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
                    exportTriggered()
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

        if (canOpenModal !== false) {
            items.push({
                label: 'Show more',
                icon: <IconExpand45 />,
                onClick: () => openModal(tileId, tabId),
            })
        }

        return items
    }, [tileId, tabId, query, canOpenModal, openModal, adapter, extraMenuItems, exportTriggered])
}

export type WebTileOpenInsightProps = Required<Pick<LemonButtonProps, 'to' | 'onClick'>>

interface UseWebTileOpenInsightArgs {
    tileId: TileId
    tabId?: string
    canOpenInsight: boolean
}

const trackOpenAsNewInsightClick = (): void => {
    void addProductIntentForCrossSell({
        from: ProductKey.WEB_ANALYTICS,
        to: ProductKey.PRODUCT_ANALYTICS,
        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
    })
}

export function useWebTileOpenInsight({
    tileId,
    tabId,
    canOpenInsight,
}: UseWebTileOpenInsightArgs): WebTileOpenInsightProps | undefined {
    const { getNewInsightUrl } = useValues(webAnalyticsModalLogic)
    const insightUrl = useMemo(
        () => (canOpenInsight ? getNewInsightUrl(tileId, tabId) : undefined),
        [canOpenInsight, getNewInsightUrl, tileId, tabId]
    )
    return insightUrl ? { to: insightUrl, onClick: trackOpenAsNewInsightClick } : undefined
}
