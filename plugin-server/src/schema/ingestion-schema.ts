/**
 * Types added to this file will be processed into the Plugin Server schema.json file and be available for validation using `ajv`
 */

/**
 *
 * written to kafka topic: clickhouse_session_replay_events
 * and from there to clickhouse table: session_replay_events
 */
export interface SummarizedSessionRecordingEvent {
    uuid: string
    first_timestamp: string
    last_timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    /**
     * @nullable
     * */
    first_url: string | undefined
    /**
     * @asType integer
     * */
    click_count: number
    /**
     * @asType integer
     * */
    keypress_count: number
    /**
     * @asType integer
     * */
    mouse_activity_count: number
    /**
     * @asType integer
     * */
    active_milliseconds: number
    /**
     * @asType integer
     * */
    console_log_count: number
    /**
     * @asType integer
     * */
    console_warn_count: number
    /**
     * @asType integer
     * */
    console_error_count: number
    /**
     * @asType integer
     * */
    size: number
}
