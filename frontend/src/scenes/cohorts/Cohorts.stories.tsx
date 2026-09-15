import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
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
        testOptions: { viewport: { width: 1300, height: 2000 } },
        featureFlags: [FEATURE_FLAGS.REALTIME_COHORT_FLAG_TARGETING],
    },
}
export default meta

type Story = StoryObj<{}>

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

const withRealtime = (cohort: CohortType, realtime: CohortType['realtime']): CohortType => ({ ...cohort, realtime })

const realtimeCohorts: CohortType[] = [
    withRealtime(createCohort(4, 'Viewed pricing this week', 4321, false), {
        state: 'ready',
        ready_at: '2023-07-03T09:40:00Z',
        build: null,
    }),
    // Just saved: the daily calculation and the realtime build run at the same time, and the page
    // has to keep the two apart.
    withRealtime(createCohort(5, 'Completed onboarding', 210, false, true), {
        state: 'building',
        ready_at: null,
        build: { phase: 'scanning', percent_complete: 45, updated_at: '2023-07-03T23:58:00Z' },
    }),
    withRealtime(
        { ...createCohort(6, 'Churn risk', 76, false), description: 'Logged in less than twice in the last month' },
        {
            state: 'needs_attention',
            ready_at: null,
            build: null,
        }
    ),
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

// The preparing cohort's tag holds a spinner for as long as its build runs, and the runner waits
// for every loader to disappear before it snapshots. These stories name the element to wait for
// instead. The runner freezes animations, so a spinner still snapshots deterministically.
const progressTestOptions = {
    waitForLoadersToDisappear: false,
    waitForSelector: '[data-attr="cohort-realtime-tag"]',
}

export const CohortsWithRealtimeStates: Story = {
    parameters: { pageUrl: urls.cohorts(), testOptions: progressTestOptions },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/cohorts/': toPaginatedResponse([...mockCohorts, ...realtimeCohorts]) },
        }),
    ],
}

export const CohortNew: Story = {
    parameters: { pageUrl: urls.cohort('new') },
    decorators: [mswDecorator({ get: cohortApiMocks })],
}

export const CohortEditDynamic: Story = {
    parameters: { pageUrl: urls.cohort(1) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/1/': mockCohorts[0], ...cohortApiMocks } })],
}

export const CohortEditRealtimeReady: Story = {
    parameters: { pageUrl: urls.cohort(4) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/4/': realtimeCohorts[0], ...cohortApiMocks } })],
}

// Pins the flag-off page: without the rollout flag, a realtime cohort must look like any dynamic cohort.
export const CohortEditRealtimeReadyFlagOff: Story = {
    parameters: { pageUrl: urls.cohort(4), featureFlags: [] },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/4/': realtimeCohorts[0], ...cohortApiMocks } })],
}

export const CohortEditRealtimePreparing: Story = {
    parameters: {
        pageUrl: urls.cohort(5),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[data-attr="cohort-realtime-status"]' },
    },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/5/': realtimeCohorts[1], ...cohortApiMocks } })],
}

export const CohortEditRealtimeRebuilding: Story = {
    parameters: {
        pageUrl: urls.cohort(5),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[data-attr="cohort-realtime-status"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/cohorts/5/': withRealtime(
                    { ...realtimeCohorts[1], is_calculating: false },
                    {
                        state: 'rebuilding',
                        ready_at: null,
                        build: { phase: 'checking', percent_complete: null, updated_at: '2023-07-03T23:58:00Z' },
                    }
                ),
                ...cohortApiMocks,
            },
        }),
    ],
}

export const CohortEditRealtimeNotAvailable: Story = {
    parameters: { pageUrl: urls.cohort(6) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/6/': realtimeCohorts[2], ...cohortApiMocks } })],
}

export const CohortEditStatic: Story = {
    parameters: { pageUrl: urls.cohort(3) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/cohorts/3/': mockCohorts[2], ...cohortApiMocks } })],
}
