import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { ActivityScope } from '~/types'

import { AgentAttribution } from './AgentAttribution'
import { ActivityLogDetail, HumanizedActivityLogItem } from './humanizeActivity'

const AGENT_TASK_ID = '019f4c2a-0000-7000-8000-0000000000aa'

function logItem(detail: Partial<ActivityLogDetail>): HumanizedActivityLogItem {
    return {
        description: 'changed the tile query on Weekly signups',
        created_at: dayjs('2026-09-14T12:00:00Z'),
        unprocessed: {
            activity: 'updated',
            created_at: '2026-09-14T12:00:00Z',
            scope: ActivityScope.DASHBOARD,
            client: 'mcp',
            detail: { merge: null, trigger: null, changes: null, name: 'Weekly signups', ...detail },
        },
    }
}

type Story = StoryObj<typeof AgentAttribution>
const meta: Meta<typeof AgentAttribution> = {
    title: 'Components/AgentAttribution',
    component: AgentAttribution,
}
export default meta

export const IntentAndTask: Story = {
    args: {
        logItem: logItem({
            trigger: {
                job_type: 'agent',
                job_id: AGENT_TASK_ID,
                payload: { intent: 'Repairing a tile that hit the query row limit, as the report asked' },
            },
        }),
    },
}

export const TaskOnly: Story = {
    args: {
        logItem: logItem({ trigger: { job_type: 'agent', job_id: AGENT_TASK_ID, payload: {} } }),
    },
}
