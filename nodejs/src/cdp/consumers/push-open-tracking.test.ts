import { buildPushOpenedMetric } from './push-open-tracking'

describe('buildPushOpenedMetric', () => {
    const flow = { id: 'wf-1', team_id: 1 }
    const props = {
        $notification_workflow_id: 'wf-1',
        $notification_invocation_id: 'inv-1',
        $notification_action_id: 'action-1',
    }

    it('builds a push_opened metric attributed to the workflow and action', () => {
        expect(buildPushOpenedMetric(props, 1, flow)).toEqual({
            team_id: 1,
            app_source_id: 'wf-1',
            instance_id: 'action-1',
            metric_name: 'push_opened',
            metric_kind: 'push',
            count: 1,
        })
    })

    it('attributes a batch open to its parent run so it divides against the batch send', () => {
        const metric = buildPushOpenedMetric({ ...props, $notification_parent_run_id: 'batch-9' }, 1, flow)
        expect(metric?.app_source_id).toBe('batch-9')
    })

    it('falls back to the invocation id for instance_id when there is no action id', () => {
        const metric = buildPushOpenedMetric(
            { $notification_workflow_id: 'wf-1', $notification_invocation_id: 'inv-1' },
            1,
            flow
        )
        expect(metric?.instance_id).toBe('inv-1')
    })

    it('leaves instance_id undefined when both action and invocation ids are empty strings', () => {
        // Empty strings must fall through to undefined, not be used as the instance_id.
        const metric = buildPushOpenedMetric(
            { $notification_workflow_id: 'wf-1', $notification_action_id: '', $notification_invocation_id: '' },
            1,
            flow
        )
        expect(metric?.instance_id).toBeUndefined()
    })

    it('does not count an event whose workflow belongs to another team', () => {
        // Guards against a spoofed $push_notification_opened inflating a different team's metrics: the
        // captured event's team (2) does not own the resolved workflow (team 1).
        expect(buildPushOpenedMetric(props, 2, flow)).toBeNull()
    })

    it('does not count an event whose workflow does not resolve to a hog flow', () => {
        expect(buildPushOpenedMetric(props, 1, null)).toBeNull()
    })

    it('does not count an event missing the workflow id', () => {
        expect(buildPushOpenedMetric({ $notification_invocation_id: 'inv-1' }, 1, flow)).toBeNull()
    })
})
