export interface AnomalyScoreType {
    id: string
    insight_id: number
    insight_name: string
    insight_short_id: string
    series_index: number
    series_label: string
    /** Timestamp of the most recent anomaly in the window. */
    timestamp: string
    /** Highest score among anomalies for this series in the window. */
    score: number
    is_anomalous: boolean
    interval: string
    data_snapshot: {
        data: number[]
        dates: string[]
        /** Indices of all anomaly points on the sparkline, oldest → newest. */
        anomaly_indices: number[]
        /** Legacy — the last entry of `anomaly_indices`. Kept for back-compat. */
        anomaly_index: number | null
        /** Per-sparkline-point anomaly score (0–1) or null when no tick scored that point. */
        scores?: (number | null)[]
    }
    scored_at: string
    /** How many anomalies this series had in the window. */
    anomaly_count: number
}

export type AnomalyWindow = '24h' | '7d' | '30d'
export type AnomalyInterval = '' | 'hour' | 'day' | 'week' | 'month'
