import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import { dashboardActivityDescriber } from 'scenes/dashboard/dashboardActivityDescriber'

import { ActivityScope, InsightShortId } from '~/types'

import { ActivityLogRow } from './ActivityLogRow'
import { describerFor } from './describers'
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
    decorators: [
        (Story) => (
            <div className="w-[calc(100vw-2rem)] max-w-3xl">
                <Story />
            </div>
        ),
    ],
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
            // Rows built by humanize() always carry the actor's email; without one the
            // avatar renders the unknown-lettermark placeholder, which the test runner
            // reads as a stuck loader.
            email: 'mia@example.com',
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

const productEvents: ActivityLogItem[] = [
    {
        ...dashboardEvents[0],
        scope: ActivityScope.INSIGHT,
        detail: {
            ...dashboardEvents[0].detail,
            name: 'Weekly signups',
            short_id: 'example1' as InsightShortId,
            changes: [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'description',
                    before: 'Count new signups.',
                    after: 'Compare completed registrations by signup method each week. Include only people who finish email verification, and use the regional breakdown to check whether the new welcome page helps more people get started.',
                },
            ],
        },
    },
    {
        ...dashboardEvents[0],
        id: '019f4c2a-0000-7000-8000-000000000003',
        scope: ActivityScope.FEATURE_FLAG,
        client: null,
        detail: {
            name: 'welcome-page',
            merge: null,
            trigger: { job_type: 'scheduled_change', job_id: 'example-schedule', payload: {} },
            changes: [
                { type: ActivityScope.FEATURE_FLAG, action: 'changed', field: 'active', before: false, after: true },
            ],
        },
    },
    {
        ...dashboardEvents[0],
        id: '019f4c2a-0000-7000-8000-000000000004',
        scope: ActivityScope.SURVEY,
        client: null,
        detail: {
            name: 'Setup feedback',
            merge: null,
            trigger: null,
            changes: [
                {
                    type: ActivityScope.SURVEY,
                    action: 'changed',
                    field: 'description',
                    before: '',
                    after: 'Ask new workspace owners which setup step could use a clearer explanation.',
                },
                {
                    type: ActivityScope.SURVEY,
                    action: 'changed',
                    field: 'start_date',
                    before: null,
                    after: '2026-09-14T10:00:00Z',
                },
            ],
        },
    },
    {
        ...dashboardEvents[0],
        id: '019f4c2a-0000-7000-8000-000000000005',
        scope: ActivityScope.ORGANIZATION_INVITE,
        activity: 'created',
        client: null,
        detail: {
            name: null,
            merge: null,
            trigger: null,
            changes: null,
            context: {
                organization_name: 'Example workspace',
                target_email: 'new-member@example.com',
                level: 'member',
                inviter_user_name: 'Example inviter',
                inviter_user_email: 'inviter@example.com',
            },
        },
    },
    {
        ...dashboardEvents[0],
        id: '019f4c2a-0000-7000-8000-000000000006',
        scope: ActivityScope.BATCH_EXPORT,
        client: null,
        detail: {
            name: 'Daily event archive',
            merge: null,
            trigger: null,
            changes: [
                {
                    type: ActivityScope.BATCH_EXPORT,
                    action: 'changed',
                    field: 'interval',
                    before: 'hour',
                    after: 'day',
                },
                {
                    type: ActivityScope.BATCH_EXPORT,
                    action: 'changed',
                    field: 'timezone',
                    before: 'UTC',
                    after: 'Europe/London',
                },
            ],
        },
    },
    {
        ...dashboardEvents[0],
        id: '019f4c2a-0000-7000-8000-000000000007',
        scope: ActivityScope.INSIGHT,
        activity: 'share_login_failed',
        user: undefined,
        client: null,
        detail: {
            name: 'Weekly signups',
            short_id: 'example1' as InsightShortId,
            merge: null,
            trigger: null,
            changes: [
                {
                    type: ActivityScope.INSIGHT,
                    action: 'changed',
                    field: 'share_login',
                    after: { client_ip: '192.0.2.1' },
                },
            ],
        },
    },
]

export const AcrossProducts: Story = {
    render: () => (
        <div className="max-w-3xl space-y-2">
            {humanize(productEvents, describerFor).map((logItem) => (
                <ActivityLogRow key={logItem.id} logItem={logItem} />
            ))}
        </div>
    ),
}

export const NarrowAcrossProducts: Story = {
    ...AcrossProducts,
    decorators: [
        (Story) => (
            <div className="w-full max-w-lg">
                <Story />
            </div>
        ),
    ],
}
