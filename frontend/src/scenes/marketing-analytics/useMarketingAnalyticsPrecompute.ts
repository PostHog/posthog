import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { DataNode, RefreshType } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

const NOT_READY_REFETCH_BASE_DELAY_MS = 30 * 1000
const NOT_READY_REFETCH_MAX_DELAY_MS = 5 * 60 * 1000
// Query log name for the automatic retries, so they are not counted as reads a person started.
export const NOT_READY_REFETCH_QUERY_NAME = 'marketing_analytics_not_ready_refetch'

export interface MarketingAnalyticsPrecomputeStatus {
    /** The window this read asked for has not been warmed yet. */
    notReady: boolean
    /** ISO timestamp of the oldest precompute window behind the result, or null when nothing was read. */
    computedAt: string | null
}

/** The precompute-only signals a marketing analytics response carries.
 *
 * Marketing analytics serves exclusively from precompute, so a cold window comes back as an empty result
 * with `precomputeNotReady` set — a tile that only looks at the rows cannot tell that apart from a team
 * with no spend. Binds the same dataNodeLogic instance the tile's own DataTable builds, so the query
 * still loads once. */
export function useMarketingAnalyticsPrecompute(
    source: DataNode,
    insightProps: InsightLogicProps
): MarketingAnalyticsPrecomputeStatus {
    const logic = dataNodeLogic({
        query: source,
        key: insightVizDataNodeKey(insightProps),
        dataNodeCollectionId: insightProps.dataNodeCollectionId,
    })
    const { response, responseLoading } = useValues(logic)
    const { loadData } = useActions(logic)
    const precomputeResponse = response as { precomputeNotReady?: boolean; dataComputedAt?: string } | null
    const notReady = !responseLoading && precomputeResponse?.precomputeNotReady === true

    useRefetchWhileNotReady(notReady, source, loadData)

    return {
        notReady,
        computedAt: precomputeResponse?.dataComputedAt ?? null,
    }
}

/** Requests a not-ready read again, with backoff, until the background warm lands, so the user does not have
 * to reload. The retry forces past the cache, because a not-ready response cached before the backend stopped
 * storing them, or retained in the browser, would otherwise come back again. Pauses while the tab is hidden. */
export function useRefetchWhileNotReady(
    notReady: boolean,
    query: DataNode,
    loadData: (refresh?: RefreshType, alreadyRunningQueryId?: string, overrideQuery?: DataNode) => void
): void {
    const { isVisible } = usePageVisibility()
    const attemptRef = useRef(0)

    useEffect(() => {
        if (!notReady) {
            attemptRef.current = 0
            return
        }
        if (!isVisible) {
            return
        }
        const delay = Math.min(
            NOT_READY_REFETCH_BASE_DELAY_MS * 2 ** attemptRef.current,
            NOT_READY_REFETCH_MAX_DELAY_MS
        )
        const timeout = window.setTimeout(() => {
            attemptRef.current += 1
            loadData('force_blocking', undefined, {
                ...query,
                tags: { ...query.tags, name: NOT_READY_REFETCH_QUERY_NAME },
            })
        }, delay)
        return () => window.clearTimeout(timeout)
    }, [notReady, isVisible, query, loadData])
}
