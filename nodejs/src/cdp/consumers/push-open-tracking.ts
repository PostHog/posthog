import type { MinimalAppMetric } from '../types'

// Push opens arrive as this captured event, emitted by the mobile SDKs when a user taps a
// notification. Its `$notification_*` properties carry the ids stamped into the push payload at send.
export const PUSH_NOTIFICATION_OPENED_EVENT = '$push_notification_opened'

// Build the `push_opened` app-metric for one $push_notification_opened event, or null if it should not
// count. The event is client-emitted (spoofable), so it only counts when its $notification_workflow_id
// resolves to a hog flow on the *same* team that captured the event — a spoofed event can't inflate
// another team's metrics. Attribution mirrors the send metric (parentRunId ?? workflowId /
// actionId ?? invocationId) so Sent and Opened divide into a rate under the same app_source_id.
export function buildPushOpenedMetric(
    properties: Record<string, unknown>,
    teamId: number,
    hogFlow: { id: string; team_id: number } | null
): MinimalAppMetric | null {
    const workflowId = properties['$notification_workflow_id']
    if (typeof workflowId !== 'string') {
        return null
    }
    if (!hogFlow || hogFlow.team_id !== teamId) {
        return null
    }
    const parentRunId = properties['$notification_parent_run_id']
    const actionId = properties['$notification_action_id']
    const invocationId = properties['$notification_invocation_id']
    return {
        team_id: hogFlow.team_id,
        app_source_id: typeof parentRunId === 'string' && parentRunId ? parentRunId : workflowId,
        instance_id:
            typeof actionId === 'string' && actionId
                ? actionId
                : typeof invocationId === 'string' && invocationId
                  ? invocationId
                  : undefined,
        metric_name: 'push_opened',
        metric_kind: 'push',
        count: 1,
    }
}
