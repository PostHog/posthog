import api from 'lib/api'

export interface ExternalFeatureFlag {
    key: string
    name: string
    description?: string
    enabled: boolean
    conditions: Array<{
        properties: Array<{
            key: string
            operator: string
            value: any
            type: string
        }>
        rollout_percentage: number
        variant?: string
        rule_id?: string
    }>
    variants: Array<{
        key: string
        name: string
        rollout_percentage?: number
        value?: any
        description?: string
        is_default?: boolean
    }>
    metadata: {
        provider: string
        original_id?: string
        created_at?: string
        updated_at?: string
        environments?: string[]
        tags?: string[]
        total_rules?: number
        has_prerequisites?: boolean
        environment_configs?: Record<
            string,
            {
                enabled: boolean
                rules_count: number
                has_targets: boolean
                target_count: number
                detailed_rules: Array<{
                    id: string
                    description: string
                    clauses: Array<{
                        attribute: string
                        operator: string
                        values: any[]
                        negate: boolean
                        context_kind: string
                    }>
                    rollout_info?: {
                        type: 'rollout' | 'direct'
                        variation?: number
                        variations?: Array<{
                            variation: number
                            weight: number
                            percentage: number
                        }>
                    }
                }>
                fallthrough?: {
                    type: 'rollout' | 'direct'
                    variation?: number
                    variations?: Array<{
                        variation: number
                        weight: number
                        percentage: number
                    }>
                }
                off_variation?: number
            }
        >
    }
    importable: boolean
    import_issues: string[]
}

export interface FetchExternalFlagsResponse {
    importable_flags: ExternalFeatureFlag[]
    non_importable_flags: ExternalFeatureFlag[]
    total_flags: number
    importable_count: number
    non_importable_count: number
}

export interface ImportFlagsResponse {
    imported_flags: Array<{
        external_flag: ExternalFeatureFlag
        posthog_flag: {
            id: number
            key: string
            name: string
            active: boolean
        }
    }>
    failed_imports: Array<{
        flag: ExternalFeatureFlag
        error: string
    }>
    success_count: number
    failure_count: number
}

export interface FieldMapping {
    external_key: string
    external_type: string
    display_name: string
    posthog_field: string | null
    posthog_type: string
    auto_selected: boolean
    options: Array<{ key: string; label: string; type: string }>
}

export interface ExtractFieldMappingsResponse {
    field_mappings: FieldMapping[]
    total_fields: number
}

export const featureFlagMigrationApi = {
    async fetchExternalFlags(
        provider: string,
        apiKey: string,
        projectKey?: string,
        environment: string = 'production'
    ): Promise<FetchExternalFlagsResponse> {
        // Use PostHog backend to proxy the request to avoid CORS issues
        const response = await api.featureFlags.fetchExternalFlags({
            provider,
            api_key: apiKey,
            environment,
            ...(projectKey ? { project_key: projectKey } : {}),
        })
        return response
    },

    async extractFieldMappings(params: {
        provider: string
        selected_flags: ExternalFeatureFlag[]
    }): Promise<ExtractFieldMappingsResponse> {
        const response = await api.featureFlags.extractFieldMappings(params)
        return response
    },

    async importFlags(
        provider: string,
        selectedFlags: ExternalFeatureFlag[],
        environment: string = 'production',
        fieldMappings: Record<string, any> = {}
    ): Promise<ImportFlagsResponse> {
        // Call the actual backend API
        const response = await api.featureFlags.importExternalFlags({
            provider,
            selected_flags: selectedFlags,
            environment,
            field_mappings: fieldMappings,
        })
        return response
    },
}
