import { Counter } from 'prom-client'

export class RetentionServiceMetrics {
    private static readonly retentionPeriodRefreshErrors = new Counter({
        name: 'recording_blob_ingestion_v2_retention_period_refresh_errors',
        help: 'Number of errors encountered while refreshing retention period settings',
    })

    private static readonly retentionPeriodRefreshCount = new Counter({
        name: 'recording_blob_ingestion_v2_retention_period_refresh_count',
        help: 'Count of retention period setting refreshes',
    })

    private static readonly retentionPeriodLookupErrors = new Counter({
        name: 'recording_blob_ingestion_v2_retention_period_lookup_errors',
        help: 'Number of errors encountered while looking up retention period settings',
    })

    public static incrementRefreshErrors(): void {
        this.retentionPeriodRefreshErrors.inc()
    }

    public static incrementRefreshCount(): void {
        this.retentionPeriodRefreshCount.inc()
    }

    public static incrementLookupErrors(): void {
        this.retentionPeriodLookupErrors.inc()
    }
}
