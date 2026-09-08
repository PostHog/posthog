import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EntityDependenciesPanel } from './EntityDependenciesPanel'

const WORKFLOWS_GROUP = [
    {
        type: 'hog_flow',
        total: 3,
        has_more: false,
        results: [
            {
                entity: {
                    type: 'hog_flow',
                    id: '019a0000-0000-0000-0000-000000000001',
                    name: 'Trial nurture',
                    url: '/workflows/019a0000-0000-0000-0000-000000000001/workflow',
                    status: 'active',
                },
                roles: ['trigger_audience'],
            },
            {
                entity: {
                    type: 'hog_flow',
                    id: '019a0000-0000-0000-0000-000000000002',
                    name: 'Churn winback with a very long workflow name that truncates',
                    url: '/workflows/019a0000-0000-0000-0000-000000000002/workflow',
                    status: 'archived',
                },
                roles: ['branch_condition', 'draft:conversion'],
            },
            {
                entity: {
                    type: 'hog_flow',
                    id: '019a0000-0000-0000-0000-000000000003',
                    name: '',
                    url: '/workflows/019a0000-0000-0000-0000-000000000003/workflow',
                    status: 'active',
                },
                roles: ['wait_condition'],
            },
        ],
    },
]

const COHORTS_GROUP = [
    {
        type: 'cohort',
        total: 2,
        has_more: false,
        results: [
            {
                entity: { type: 'cohort', id: '12', name: 'Trial users', url: '/cohorts/12', status: 'active' },
                roles: ['trigger_audience'],
            },
            {
                entity: { type: 'cohort', id: '99', name: '', url: '', status: 'missing' },
                roles: ['conversion'],
            },
        ],
    },
]

const meta: Meta<typeof EntityDependenciesPanel> = {
    title: 'Components/Entity Dependencies Panel',
    component: EntityDependenciesPanel,
    render: (args) => (
        <div className="w-60">
            <EntityDependenciesPanel {...args} />
        </div>
    ),
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof EntityDependenciesPanel>

export const UsedBy: Story = {
    args: { type: 'cohort', id: '12', direction: 'used_by' },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/dependencies/': WORKFLOWS_GROUP } })],
}

export const DependsOn: Story = {
    args: { type: 'hog_flow', id: '019a0000-0000-0000-0000-000000000001', direction: 'depends_on' },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/dependencies/': COHORTS_GROUP } })],
}

export const Empty: Story = {
    args: { type: 'cohort', id: '13', direction: 'used_by' },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/dependencies/': [] } })],
}
