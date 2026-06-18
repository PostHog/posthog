import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

// Two folder-navigation paradigms tested against today's flat list: `explorer` (drill-in finder) and
// `tree` (persistent folder tree beside the content). The old `grid` arm was dropped — see the design spec.
export type DashboardsListViewVariant = 'control' | 'explorer' | 'tree'

const DEFAULT_VARIANT: DashboardsListViewVariant = 'control'

export const DASHBOARDS_LIST_VIEW_VARIANTS: DashboardsListViewVariant[] = ['control', 'explorer', 'tree']

// Resolves the `dashboards-list-view` multivariate flag to a known arm, defaulting to control
// so a missing, unknown, boolean, or empty flag value never silently enrolls a project in a treatment arm.
export function resolveDashboardsListViewVariant(featureFlags: FeatureFlagsSet): DashboardsListViewVariant {
    const variant = featureFlags[FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]
    return typeof variant === 'string' && (DASHBOARDS_LIST_VIEW_VARIANTS as string[]).includes(variant)
        ? (variant as DashboardsListViewVariant)
        : DEFAULT_VARIANT
}
