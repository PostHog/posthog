import { HumanizedActivityLogItem, Trigger } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'

import { ActivityScope } from '~/types'

import { SandboxChange, sandboxChange } from './sandboxChange'

const AGENT_TASK_ID = '019f4c2a-0000-7000-8000-0000000000aa'

describe('sandboxChange', () => {
    function logItem(client: string | null, trigger: Trigger | null): HumanizedActivityLogItem {
        return {
            description: 'changed the tile query on Weekly signups',
            created_at: dayjs('2026-09-14T12:00:00Z'),
            unprocessed: {
                activity: 'updated',
                created_at: '2026-09-14T12:00:00Z',
                scope: ActivityScope.DASHBOARD,
                client,
                ip_address: '198.51.100.24',
                detail: { merge: null, trigger, changes: null, name: 'Weekly signups' },
            },
        }
    }

    it.each([
        [
            'a scout run, whose client tag already names the scout',
            'scout:signals-scout-errors',
            { job_type: 'agent', job_id: AGENT_TASK_ID, payload: {} },
            { needsSandboxTag: false },
        ],
        [
            'another sandbox task',
            'mcp',
            { job_type: 'agent', job_id: AGENT_TASK_ID, payload: {} },
            { needsSandboxTag: true },
        ],
        [
            'an agent with intent but no task binding',
            'mcp',
            { job_type: 'agent', job_id: '', payload: { intent: 'Repairing a broken tile' } },
            null,
        ],
        ['a self-reported client', 'posthog-js/1.234.0', null, null],
        ['a background job', null, { job_type: 'hog_flow', job_id: '1234', payload: {} }, null],
    ] as [string, string | null, Trigger | null, SandboxChange | null][])(
        'reads %s',
        (_label, client, trigger, expected) => {
            expect(sandboxChange(logItem(client, trigger))).toEqual(expected)
        }
    )
})
