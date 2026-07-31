import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

// One folder-navigation paradigm tested against today's flat list: `tree` (a persistent folder-tree panel
// beside the table). The `grid` and `explorer` arms were both dropped before launch — see the design spec.
// Experiment cleanup: flag `dashboards-list-view` · experiment 379125 — remove this resolver and the tree arm
// when the experiment concludes.
export type DashboardsListViewVariant = 'control' | 'tree'

const DEFAULT_VARIANT: DashboardsListViewVariant = 'control'

export const DASHBOARDS_LIST_VIEW_VARIANTS: DashboardsListViewVariant[] = ['control', 'tree']

// Resolves the `dashboards-list-view` multivariate flag to a known arm, defaulting to control
// so a missing, unknown, boolean, or empty flag value never silently enrolls a project in a treatment arm.
export function resolveDashboardsListViewVariant(featureFlags: FeatureFlagsSet): DashboardsListViewVariant {
    const variant = featureFlags[FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]
    return typeof variant === 'string' && (DASHBOARDS_LIST_VIEW_VARIANTS as string[]).includes(variant)
        ? (variant as DashboardsListViewVariant)
        : DEFAULT_VARIANT
}
