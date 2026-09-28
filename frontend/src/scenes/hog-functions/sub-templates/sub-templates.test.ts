import { eventToHogFunctionContextId } from './sub-templates'

describe('sub-templates', () => {
    // One event per product that creates internal destinations. An id missing from the switch
    // falls back to 'standard', which merges that product into the notification list's "Other"
    // source and drops its source tag.
    it.each([
        ['$error_tracking_issue_created', 'error-tracking'],
        ['$insight_alert_firing', 'insight-alerts'],
        ['$experiment_metric_significant', 'experiment-alerts'],
        ['$activity_log_entry_created', 'activity-log'],
        ['$discussion_mention_created', 'discussion-mention'],
        ['$logs_alert_firing', 'logs-alerting'],
        ['$health_check_issue_firing', 'health-alerts'],
        ['$batch_export_run_failed', 'batch-export-alerts'],
        ['$billing_alert_firing', 'billing-alerts'],
        ['$replay_vision_alert_match', 'replay-vision-alerts'],
        ['$pageview', 'standard'],
        [undefined, 'standard'],
    ])('reads %s as the %s context', (event, expected) => {
        expect(eventToHogFunctionContextId(event)).toBe(expected)
    })
})
