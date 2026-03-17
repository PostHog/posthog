import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryFn } from '@storybook/react'

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

export const Dynamic: StoryFn = () => <CohortView cohort={dynamicCohort} />
Dynamic.storyName = 'Dynamic cohort'

export const Static: StoryFn = () => <CohortView cohort={staticCohort} />
Static.storyName = 'Static cohort'

export const Calculating: StoryFn = () => <CohortView cohort={calculatingCohort} />
Calculating.storyName = 'Calculating cohort'

const sampleListData: CohortListData = {
    results: [dynamicCohort, staticCohort, calculatingCohort],
    _posthogUrl: 'https://us.posthog.com/project/1/cohorts',
}

export const List: StoryFn = () => <CohortListView data={sampleListData} />
List.storyName = 'Cohort list'
