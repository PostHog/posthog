import { Counter } from 'prom-client'

export class TeamServiceMetrics {
    private static readonly teamTokenRefreshErrors = new Counter({
        name: 'recording_blob_ingestion_v2_team_tokens_refresh_errors',
        help: 'Number of errors encountered while refreshing team tokens',
    })

    private static readonly teamTokenRefreshCount = new Counter({
        name: 'recording_blob_ingestion_v2_team_tokens_refresh_count',
        help: 'Count of team token refreshes',
    })

    private static readonly teamTokenMisses = new Counter({
        name: 'recording_blob_ingestion_v2_team_token_misses',
        help: 'Count of token lookups that miss the cached team list, by the outcome of the refresh on miss',
        labelNames: ['outcome'],
    })

    public static incrementRefreshErrors(): void {
        this.teamTokenRefreshErrors.inc()
    }

    public static incrementRefreshCount(): void {
        this.teamTokenRefreshCount.inc()
    }

    public static incrementTokenMiss(outcome: 'found_after_refresh' | 'not_found' | 'refresh_skipped'): void {
        this.teamTokenMisses.inc({ outcome })
    }
}
