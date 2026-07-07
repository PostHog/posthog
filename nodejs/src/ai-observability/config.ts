export type AIObservabilityConfig = {
    // Temporal — used by TemporalService to start evaluation-run workflows
    TEMPORAL_HOST: string
    TEMPORAL_PORT: string | undefined
    TEMPORAL_NAMESPACE: string
    TEMPORAL_CLIENT_ROOT_CA: string | undefined
    TEMPORAL_CLIENT_CERT: string | undefined
    TEMPORAL_CLIENT_KEY: string | undefined

    TEMPORAL_SECRET_KEY: string | undefined
    TEMPORAL_FALLBACK_SECRET_KEYS: string
    LLMA_EVAL_SCHEDULER_PROVIDER_KEY_GATING: boolean
}

export function getDefaultAIObservabilityConfig(): AIObservabilityConfig {
    return {
        TEMPORAL_HOST: 'localhost',
        TEMPORAL_PORT: '7233',
        TEMPORAL_NAMESPACE: 'default',
        TEMPORAL_CLIENT_ROOT_CA: undefined,
        TEMPORAL_CLIENT_CERT: undefined,
        TEMPORAL_CLIENT_KEY: undefined,
        TEMPORAL_SECRET_KEY: process.env.TEMPORAL_SECRET_KEY ?? process.env.SECRET_KEY,
        TEMPORAL_FALLBACK_SECRET_KEYS: process.env.TEMPORAL_FALLBACK_SECRET_KEYS ?? '',
        LLMA_EVAL_SCHEDULER_PROVIDER_KEY_GATING: false,
    }
}
