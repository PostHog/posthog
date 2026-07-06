import { Counter } from 'prom-client'

export class RetentionServiceMetrics {
    private static readonly retentionPeriodLookupErrors = new Counter({
        name: 'recording_blob_ingestion_v2_retention_period_lookup_errors',
        help: 'Number of errors encountered while looking up retention period settings',
    })

    public static incrementLookupErrors(): void {
        this.retentionPeriodLookupErrors.inc()
    }
}
