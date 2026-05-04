export type LlmAnalyticsConfig = {
    // Temporal — used by TemporalService to start evaluation-run workflows
    TEMPORAL_HOST: string
    TEMPORAL_PORT: string | undefined
    TEMPORAL_NAMESPACE: string
    TEMPORAL_CLIENT_ROOT_CA: string | undefined
    TEMPORAL_CLIENT_CERT: string | undefined
    TEMPORAL_CLIENT_KEY: string | undefined
}

export function getDefaultLlmAnalyticsConfig(): LlmAnalyticsConfig {
    return {
        TEMPORAL_HOST: 'localhost',
        TEMPORAL_PORT: '7233',
        TEMPORAL_NAMESPACE: 'default',
        TEMPORAL_CLIENT_ROOT_CA: undefined,
        TEMPORAL_CLIENT_CERT: undefined,
        TEMPORAL_CLIENT_KEY: undefined,
    }
}
