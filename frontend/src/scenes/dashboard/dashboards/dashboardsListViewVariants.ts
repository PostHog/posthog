import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export type DashboardsListViewVariant = 'control' | 'grid' | 'finder'

const DEFAULT_VARIANT: DashboardsListViewVariant = 'control'

export const DASHBOARDS_LIST_VIEW_VARIANTS: DashboardsListViewVariant[] = ['control', 'grid', 'finder']

// Resolves the `dashboards-list-view` multivariate flag to a known arm, defaulting to control
// so a missing, unknown, boolean, or empty flag value never silently enrolls a project in a treatment arm.
export function resolveDashboardsListViewVariant(featureFlags: FeatureFlagsSet): DashboardsListViewVariant {
    const variant = featureFlags[FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]
    return typeof variant === 'string' && (DASHBOARDS_LIST_VIEW_VARIANTS as string[]).includes(variant)
        ? (variant as DashboardsListViewVariant)
        : DEFAULT_VARIANT
}
