// Noise/outlier cluster ID from HDBSCAN
export const NOISE_CLUSTER_ID = -1

// Color for outlier/noise cluster
export const OUTLIER_COLOR = '#888888'

// Pagination
export const TRACES_PER_PAGE = 50

// Query limits
export const MAX_CLUSTERING_RUNS = 20

// How far back to look for clustering runs. Scheduled runs are emitted (roughly) daily, but
// a team can go several days without a fresh run — low-traffic days, sampling, or a paused
// schedule. A wide window keeps the most recent run visible instead of the page going empty
// the moment the last run ages past a day or two. MAX_CLUSTERING_RUNS still bounds the result.
export const CLUSTERING_RUNS_LOOKBACK_DAYS = 90

// Cluster detail URL pattern. Mirrored in `manifest.tsx`'s route registration so any
// `urlToAction` matcher (e.g. `clusterDetailLogic`, `aiObservabilitySharedLogic`)
// stays in lockstep with the actual route.
export const AI_OBSERVABILITY_CLUSTER_URL_PATTERN = '/ai-observability/clusters/:runId/:clusterId'

// Scene names used as ClickHouse query tags. These match the route registrations in
// `manifest.tsx`, and the query runner pulls them off `query.tags.scene` to attach to
// every executed query for analytics. Centralised so the tags don't drift if the scene
// names ever change.
export const AI_OBSERVABILITY_CLUSTERS_SCENE_TAG = 'AIObservabilityClusters'
export const AI_OBSERVABILITY_CLUSTER_SCENE_TAG = 'AIObservabilityCluster'

// Cluster items are keyed by UUIDs from precomputed clustering events. Restrict to
// hex / dashes before interpolating into a HogQL `IN` literal so a malformed key
// can't break out of the string. UUIDs already match this character set.
export const SAFE_ID_RE = /^[a-f0-9-]+$/i

// Mirrors `MAX_SELECT_RETURNED_ROWS` in `posthog/hogql/constants.py`. EventsQuery rows above
// this are silently truncated server-side, so post-hoc property-filter queries against the
// full set of cluster items must either fit under the cap or fall back to "no filtering".
export const FILTER_QUERY_MAX_ROWS = 50000

/**
 * Centroid detection for chart.js scatter datasets.
 *
 * Two label shapes exist:
 *   - Overview plot (ClusterScatterPlot): per-cluster label with "(centroid)" suffix,
 *     e.g. "Auth failures (centroid)" — so one cluster's points and centroid stay visually paired.
 *   - Single-cluster detail plot (ClusterDetailScatterPlot): just "Centroid" since the dataset
 *     only holds one cluster's worth of data.
 *
 * Centralising keeps tooltip/click suppression in sync across both views.
 */
export function isCentroidDataset(dataset: { label?: string } | undefined | null): boolean {
    const label = dataset?.label
    if (!label) {
        return false
    }
    return label === 'Centroid' || label.includes('(centroid)')
}
