export interface EventPipelineRunnerOptions {
    SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: boolean
    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: number
    PERSON_MERGE_ASYNC_ENABLED: boolean
    PERSON_MERGE_SYNC_BATCH_SIZE: number
    PERSON_MERGE_EVENTS_ENABLED: boolean
    PERSON_MERGE_EVENTS_PARTITION_COUNT: number
    PERSON_MERGE_EVENTS_TEAM_ALLOWLIST: string
    PERSON_JSONB_SIZE_ESTIMATE_ENABLE: number
    PERSON_PROPERTIES_UPDATE_ALL: boolean
    /** Teams whose $feature_flag_called events default to personless: '*' for all, '' to disable, or comma-separated team IDs */
    FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS: string
}
