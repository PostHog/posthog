import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { CohortListView, type CohortData, type CohortListData, CohortView } from './index'

const meta: Meta = {
    title: 'MCP Apps/Cohorts',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const dynamicCohort: CohortData = {
    id: 1,
    name: 'Power users',
    description: 'Users who performed 10+ events in the last 30 days.',
    is_static: false,
    is_calculating: false,
    count: 4320,
    created_at: '2025-10-01T09:00:00Z',
    created_by: { first_name: 'Jane', email: 'jane@posthog.com' },
    _posthogUrl: 'https://us.posthog.com/project/1/cohorts/1',
}

const staticCohort: CohortData = {
    id: 2,
    name: 'Beta testers batch 3',
    description: 'Manually uploaded list of beta program participants.',
    is_static: true,
    is_calculating: false,
    count: 150,
    created_at: '2025-11-15T09:00:00Z',
    created_by: { first_name: 'Alex' },
    _posthogUrl: 'https://us.posthog.com/project/1/cohorts/2',
}

const calculatingCohort: CohortData = {
    id: 3,
    name: 'Churned users',
    description: 'Users who have not logged in for 60+ days.',
    is_static: false,
    is_calculating: true,
    count: null,
    created_at: '2025-12-01T09:00:00Z',
}

// Mirrors the minimized cohorts-retrieve payload, which keeps only created_by.id.
const idOnlyCreatorCohort: CohortData = {
    id: 4,
    name: 'Recently active',
    description: 'Users seen in the last 7 days.',
    is_static: false,
    is_calculating: false,
    count: 980,
    created_at: '2026-01-10T09:00:00Z',
    created_by: { id: 42 },
    _posthogUrl: 'https://us.posthog.com/project/1/cohorts/4',
}

export const Dynamic: Story = {
    render: () => <CohortView cohort={dynamicCohort} />,
    name: 'Dynamic cohort',
}

export const Static: Story = {
    render: () => <CohortView cohort={staticCohort} />,
    name: 'Static cohort',
}

export const Calculating: Story = {
    render: () => <CohortView cohort={calculatingCohort} />,
    name: 'Calculating cohort',
}

export const IdOnlyCreator: Story = {
    render: () => <CohortView cohort={idOnlyCreatorCohort} />,
    name: 'Creator without a displayable name',
}

const sampleListData: CohortListData = {
    results: [dynamicCohort, staticCohort, calculatingCohort],
    _posthogUrl: 'https://us.posthog.com/project/1/cohorts',
}

export const List: Story = {
    render: () => <CohortListView data={sampleListData} />,
    name: 'Cohort list',
}
