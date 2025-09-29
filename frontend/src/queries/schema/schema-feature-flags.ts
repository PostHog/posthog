// Feature flag schema definitions for Max AI tools

// Re-export types that are already defined in types.ts for schema consistency
export type FeatureFlagEvaluationRuntime = 'server' | 'client' | 'all'

// Feature flag variant schema
export interface FeatureFlagVariantSchema {
    key: string
    name?: string
    rollout_percentage: number
}

// Feature flag filters schema matching PostHog FeatureFlag model format
export interface FeatureFlagFiltersSchema {
    groups: Array<Record<string, any>>
    multivariate?: Record<string, any>
    payloads?: Record<string, any>
}

// Feature flag creation schema matching PostHog FeatureFlag model format
// Note: 'key' is the unique identifier, 'name' contains the description (UI field mapping)
export interface FeatureFlagCreationSchema {
    key: string
    name: string // This field stores what the UI calls "description"
    active?: boolean
    filters: FeatureFlagFiltersSchema
    rollout_percentage?: number
    variants?: FeatureFlagVariantSchema[]
    ensure_experience_continuity?: boolean
    evaluation_runtime?: FeatureFlagEvaluationRuntime
}
