import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export type DataOpsVariant = 'trino' | 'duckdb'

// Mirrors data_ops_variant in products/managed_warehouse/backend/presentation/views.py.
// The backend enforces the same rule, so a change here needs the same change there.
export function dataOpsVariantFromFlags(featureFlags: FeatureFlagsSet): DataOpsVariant | null {
    if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE_TRINO]) {
        return 'trino'
    }
    if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        return 'duckdb'
    }
    return null
}
