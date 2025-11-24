import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { CohortType } from '~/types'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/People/Cohorts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
    },
}
export default meta

type Story = StoryObj<typeof meta>

const createCohort = (id: number, name: string, count: number, isStatic: boolean, isCalculating = false): CohortType =>
    ({
        id,
        name,
        count,
        is_static: isStatic,
        is_calculating: isCalculating,
        last_calculation: isStatic ? null : '2023-07-03T10:00:00Z',
        created_by: { id: 1, uuid: 'user-1', distinct_id: 'user-1', first_name: 'Jane', email: 'jane@posthog.com' },
        created_at: '2023-06-15T10:00:00Z',
        deleted: false,
        filters: { properties: { type: 'AND', values: [] } },
        groups: [],
    }) as CohortType

const mockCohorts: CohortType[] = [
    createCohort(1, 'Active users', 1234, false),
    createCohort(2, 'Power users', 567, false),
    createCohort(3, 'Beta testers', 89, true),
]

const cohortApiMocks = {
    '/api/projects/:team_id/actions/': toPaginatedResponse([]),
    '/api/projects/:team_id/cohorts/': toPaginatedResponse(mockCohorts),
}

export const CohortsList: Story = { parameters: { pageUrl: urls.cohorts() } }

export const CohortsWithData: Story = {
    parameters: { pageUrl: urls.cohorts() },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/cohorts/': toPaginatedResponse(mockCohorts) },
        }),
    ],
}

export const CohortsEmpty: Story = {
    parameters: { pageUrl: urls.cohorts() },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/': toPaginatedResponse([]) } })],
}

export const CohortNew: Story = {
    parameters: { pageUrl: urls.cohort('new') },
    decorators: [mswDecorator({ get: cohortApiMocks })],
}

export const CohortEditDynamic: Story = {
    parameters: { pageUrl: urls.cohort(1) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/1/': mockCohorts[0], ...cohortApiMocks } })],
}

export const CohortEditStatic: Story = {
    parameters: { pageUrl: urls.cohort(3) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/3/': mockCohorts[2], ...cohortApiMocks } })],
}
