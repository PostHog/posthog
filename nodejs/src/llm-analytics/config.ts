export type LlmAnalyticsConfig = {
    // Temporal — used by TemporalService to start evaluation-run workflows
    TEMPORAL_HOST: string
    TEMPORAL_PORT: string | undefined
    TEMPORAL_NAMESPACE: string
    TEMPORAL_CLIENT_ROOT_CA: string | undefined
    TEMPORAL_CLIENT_CERT: string | undefined
    TEMPORAL_CLIENT_KEY: string | undefined

    // Topic the evaluation scheduler reads from. 'events' is the legacy shared
    // events topic; 'ai_events' is the AI-only topic which carries the
    // unstripped payload required for teams that have heavy props stripped from
    // the events topic. Two scheduler deployments run in parallel during the
    // rollout: one on each topic, partitioning teams between them via
    // LLMA_EVAL_SCHEDULER_AI_TOPIC_TEAMS — the AI-events deployment processes
    // teams in that list, the events deployment processes everything else.
    // Must be a superset of the strip-heavy team list, otherwise evals and
    // taggers silently break for teams in the difference set (status quo bug).
    LLMA_EVAL_SCHEDULER_TOPIC: 'events' | 'ai_events'
    LLMA_EVAL_SCHEDULER_AI_TOPIC_TEAMS: string
}

export function getDefaultLlmAnalyticsConfig(): LlmAnalyticsConfig {
    return {
        TEMPORAL_HOST: 'localhost',
        TEMPORAL_PORT: '7233',
        TEMPORAL_NAMESPACE: 'default',
        TEMPORAL_CLIENT_ROOT_CA: undefined,
        TEMPORAL_CLIENT_CERT: undefined,
        TEMPORAL_CLIENT_KEY: undefined,
        LLMA_EVAL_SCHEDULER_TOPIC: 'events',
        LLMA_EVAL_SCHEDULER_AI_TOPIC_TEAMS: '',
    }
}
