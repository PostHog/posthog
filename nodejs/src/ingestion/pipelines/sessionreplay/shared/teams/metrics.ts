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

    public static incrementRefreshErrors(): void {
        this.teamTokenRefreshErrors.inc()
    }

    public static incrementRefreshCount(): void {
        this.teamTokenRefreshCount.inc()
    }
}
