import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { hogql } from 'lib/utils/hogql'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { clusteringConfigLogic } from '../clusters/clusteringConfigLogic'
import { CLUSTERING_RUNS_LOOKBACK_DAYS } from '../clusters/constants'
import { llmAnalyticsClusteringConfigList } from '../generated/api'

const CLUSTERING_RUN_EVENTS = ['$ai_trace_clusters', '$ai_generation_clusters', '$ai_evaluation_clusters']

/**
 * Setup detection for the clusters empty state. Three-state: a clustering run at
 * any level → has-data; opted in with no run → waiting-for-data; off → needs-setup.
 * The lookback matches the scene's own run query so both agree on "no runs".
 */
export const clustersSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.LLM_CLUSTERS,
    path: ['products', 'ai_observability', 'frontend', 'emptyState', 'clustersSetupLogic'],
    recheckActionTypes: () => [clusteringConfigLogic.actionTypes.saveEnabledSuccess],
    detect: async () => {
        const response = await api.queryHogQL(
            hogql`SELECT 1 FROM events WHERE event IN ${CLUSTERING_RUN_EVENTS} AND timestamp >= now() - INTERVAL ${hogql.raw(String(CLUSTERING_RUNS_LOOKBACK_DAYS))} DAY LIMIT 1`,
            { productKey: ProductKey.AI_OBSERVABILITY, scene: 'AIObservabilityClusters' },
            { refresh: 'force_blocking' }
        )
        if ((response.results?.length ?? 0) > 0) {
            return 'has-data'
        }
        const config = await llmAnalyticsClusteringConfigList(String(teamLogic.values.currentTeamIdStrict))
        return config.enabled ? 'waiting-for-data' : 'needs-setup'
    },
    pollIntervalMs: 30000,
})
