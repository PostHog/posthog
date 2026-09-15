import { dayjs } from 'lib/dayjs'

import { ActivityScope } from '~/types'

import { agentAttribution } from './agentAttribution'
import { HumanizedActivityLogItem, Trigger } from './humanizeActivity'

const AGENT_TASK_ID = '019f4c2a-0000-7000-8000-0000000000aa'

describe('agentAttribution', () => {
    function logItem(trigger: Trigger | null): HumanizedActivityLogItem {
        return {
            description: 'changed the tile query on Weekly signups',
            created_at: dayjs('2026-09-14T12:00:00Z'),
            unprocessed: {
                activity: 'updated',
                created_at: '2026-09-14T12:00:00Z',
                scope: ActivityScope.DASHBOARD,
                detail: { merge: null, trigger, changes: null, name: 'Weekly signups' },
            },
        }
    }

    it.each([
        ['no trigger at all', null, null],
        [
            'a product trigger, whose job id is not a task',
            { job_type: 'hog_flow', job_id: '1234', payload: {} },
            null,
        ],
        ['an agent trigger carrying neither field', { job_type: 'agent', job_id: '', payload: {} }, null],
        [
            'an agent trigger with both fields',
            { job_type: 'agent', job_id: AGENT_TASK_ID, payload: { intent: 'Repairing a broken tile' } },
            { intent: 'Repairing a broken tile', taskId: AGENT_TASK_ID },
        ],
        [
            'an agent outside a sandbox task',
            { job_type: 'agent', job_id: '', payload: { intent: 'Repairing a broken tile' } },
            { intent: 'Repairing a broken tile', taskId: null },
        ],
        [
            'an agent trigger whose intent is not a string',
            { job_type: 'agent', job_id: AGENT_TASK_ID, payload: { intent: { nested: true } } },
            { intent: null, taskId: AGENT_TASK_ID },
        ],
    ] as [string, Trigger | null, ReturnType<typeof agentAttribution>][])(
        'reads %s',
        (_label, trigger, expected) => {
            expect(agentAttribution(logItem(trigger))).toEqual(expected)
        }
    )
})
