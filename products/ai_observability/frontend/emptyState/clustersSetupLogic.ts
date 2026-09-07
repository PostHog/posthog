import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import { CLUSTERING_RUNS_LOOKBACK_DAYS } from '../clusters/constants'
import { hasRecentAIEvents } from '../utils/aiEvents'

const CLUSTERING_RUN_EVENTS = ['$ai_trace_clusters', '$ai_generation_clusters', '$ai_evaluation_clusters']

/**
 * Setup detection for the clusters empty state. Three-state: a clustering run at
 * any level → has-data; AI events flowing but no run yet → waiting-for-data (runs
 * are scheduled, so the first one lags the first trace); no AI events → needs-setup.
 * The lookback matches the scene's own run query so both agree on "no runs".
 */
export const clustersSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.LLM_CLUSTERS,
    path: ['products', 'ai_observability', 'frontend', 'emptyState', 'clustersSetupLogic'],
    detect: async () => {
        const response = await api.queryHogQL(
            hogql`SELECT 1 FROM events WHERE event IN ${CLUSTERING_RUN_EVENTS} AND timestamp >= now() - INTERVAL ${hogql.raw(String(CLUSTERING_RUNS_LOOKBACK_DAYS))} DAY LIMIT 1`,
            { productKey: ProductKey.AI_OBSERVABILITY, scene: 'AIObservabilityClusters' },
            { refresh: 'force_blocking' }
        )
        if ((response.results?.length ?? 0) > 0) {
            return 'has-data'
        }
        return (await hasRecentAIEvents()) ? 'waiting-for-data' : 'needs-setup'
    },
    // Runs are emitted about once a day, so a slow poll is enough to flip the
    // screen; the wizard flow is what needs the needs-setup → waiting flip.
    pollIntervalMs: 30000,
})
