// Monitor state is computed from ClickHouse events, not stored in Postgres
export enum MonitorState {
    Healthy = 'healthy',
    Failing = 'failing',
    Error = 'error',
    Disabled = 'disabled',
}

export interface SyntheticMonitor {
    id: string
    name: string
    url: string
    frequency_minutes: 1 | 5 | 15 | 30 | 60
    regions: string[]
    method: string
    headers: Record<string, string> | null
    body: string | null
    expected_status_code: number
    timeout_seconds: number
    alert_enabled: boolean
    alert_threshold_failures: number
    alert_recipient_ids: string[]
    slack_integration_id: string | null
    enabled: boolean
    last_alerted_at: string | null
    // Computed from ClickHouse events (not stored in Postgres):
    // state: MonitorState
    // last_checked_at: string | null
    // consecutive_failures: number
    created_by: {
        id: string
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    } | null
    created_at: string
    updated_at: string
}

export interface SyntheticMonitorCheckEvent {
    monitor_id: string
    monitor_name: string
    url: string
    method: string
    region: string
    success: boolean
    status_code: number | null
    response_time_ms: number | null
    error_message: string | null
    expected_status_code: number
    consecutive_failures: number
    timestamp: string
}

export enum SyntheticMonitoringTab {
    Monitors = 'monitors',
    Settings = 'settings',
}
