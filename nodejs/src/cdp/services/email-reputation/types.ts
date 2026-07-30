/** One hourly bucket of email metrics from app_metrics2 (timestamps there are hour-truncated).
 * `appSourceId` is usually a HogFlow id but can be a batch-job id; rows that don't match a
 * HogFlow still count toward the team aggregate. */
export interface HourlyEmailMetricsRow {
    teamId: number
    appSourceId: string
    /** Epoch seconds of the hour bucket (avoids timezone-ambiguous datetime strings). */
    hourBucket: number
    sent: number
    bounced: number
    complained: number
}

/** Counts returned by a batch evaluation — snapshot rows never ride Temporal workflow history. */
export interface BatchEvaluationSummary {
    teamsEvaluated: number
    workflowsEvaluated: number
    snapshotsWritten: number
}
