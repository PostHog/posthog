import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import { dashboardActivityDescriber } from 'scenes/dashboard/dashboardActivityDescriber'

import { ActivityScope } from '~/types'

import { ActivityLogRow } from './ActivityLogRow'
import { ActivityLogItem, humanize } from './humanizeActivity'

const dashboardEvents: ActivityLogItem[] = [
    {
        id: '019f4c2a-0000-7000-8000-000000000001',
        activity: 'updated',
        scope: ActivityScope.DASHBOARD,
        item_id: '42',
        created_at: '2026-09-14T10:00:00Z',
        user: { first_name: 'Mia', last_name: 'Chen', email: 'mia@example.com' },
        client: 'mcp',
        detail: {
            name: 'Activation overview',
            merge: null,
            trigger: {
                job_type: 'agent',
                job_id: '019f4c2a-0000-7000-8000-0000000000aa',
                payload: { intent: 'Clarify which onboarding steps the report covers.' },
            },
            changes: [
                {
                    type: ActivityScope.DASHBOARD,
                    action: 'changed',
                    field: 'description',
                    before: 'Review setup progress for new workspaces.',
                    after: 'Follow a new workspace from its first invitation through its first shared report. Use this dashboard during the onboarding review to spot stalled setup steps, compare completed checklists, and decide which help articles need clearer examples.',
                },
            ],
        },
    },
    {
        id: '019f4c2a-0000-7000-8000-000000000002',
        activity: 'created',
        scope: ActivityScope.DASHBOARD,
        item_id: '42',
        created_at: '2026-09-14T09:55:00Z',
        user: { first_name: 'Mia', last_name: 'Chen', email: 'mia@example.com' },
        client: 'mcp',
        detail: {
            name: 'Activation overview',
            merge: null,
            changes: null,
            trigger: {
                job_type: 'agent',
                job_id: '019f4c2a-0000-7000-8000-0000000000aa',
                payload: {
                    intent: 'Create a dashboard for the onboarding review so the team can find where setup stops and check whether the new help articles make those steps easier to complete.',
                },
            },
        },
    },
]

const logItems = humanize(dashboardEvents, () => dashboardActivityDescriber, true)

const meta: Meta<typeof ActivityLogRow> = {
    title: 'Components/ActivityLogRow',
    component: ActivityLogRow,
    parameters: { mockDate: '2026-09-14T12:00:00Z' },
}
export default meta
type Story = StoryObj<typeof ActivityLogRow>

export const DashboardChanges: Story = {
    render: () => (
        <div className="max-w-3xl space-y-2">
            {logItems.map((logItem) => (
                <ActivityLogRow key={logItem.id} logItem={logItem} />
            ))}
        </div>
    ),
}

export const NarrowDashboardChanges: Story = {
    ...DashboardChanges,
    parameters: { layout: 'padded', viewport: { defaultViewport: 'tablet' } },
    decorators: [
        (Story) => (
            <div className="w-full max-w-lg">
                <Story />
            </div>
        ),
    ],
}

export const HumanChange: Story = {
    args: {
        logItem: humanize(
            [{ ...dashboardEvents[0], client: null, detail: { ...dashboardEvents[0].detail, trigger: null } }],
            () => dashboardActivityDescriber
        )[0],
    },
}

export const LegacyDescription: Story = {
    args: {
        logItem: {
            name: 'Mia Chen',
            description: (
                <>
                    <strong>Mia Chen</strong> enabled <strong>onboarding-checklist</strong>
                </>
            ),
            created_at: dayjs('2026-09-14T10:00:00Z'),
        },
    },
}

export const ExpandedView: Story = {
    args: {
        logItem: {
            ...logItems[0],
            extendedDescription: <div>Last 7 days</div>,
            expandedView: { label: 'Filter details', content: <div>Onboarding events from the last 7 days</div> },
        },
        highlighted: true,
    },
}
