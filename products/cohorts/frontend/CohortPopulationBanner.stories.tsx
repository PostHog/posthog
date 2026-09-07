import { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useMountedLogic } from 'kea'

import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { CohortPopulationType, CohortType } from '~/types'

import { CohortPopulationBanner } from './CohortPopulationBanner'

const COHORT_ID = 1

const meta: Meta = {
    title: 'Scenes-App/People/Cohorts/Population banner',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-09-07',
    },
}
export default meta

const BASE_POPULATION: CohortPopulationType = {
    id: 'op-1',
    source: 'list',
    status: 'running',
    phase: 'writing_membership',
    progress: { identifiers_total: 2000, identifiers_written: 1000, matched: 900, unmatched: 100 },
    error_code: '',
    error_message: null,
    attempts: 0,
    max_attempts: 6,
    next_attempt_at: null,
    input_expires_at: null,
    input_available: true,
    available_actions: ['abandon'],
    created_at: '2026-09-07T10:00:00Z',
    finished_at: null,
}

function Banner({ population }: { population: CohortPopulationType }): JSX.Element {
    return (
        <BindLogic logic={cohortEditLogic} props={{ id: COHORT_ID }}>
            <StoryCanvas population={population} />
        </BindLogic>
    )
}

function StoryCanvas({ population }: { population: CohortPopulationType }): JSX.Element {
    useMountedLogic(cohortEditLogic)
    useStorybookMocks({
        get: {
            [`/api/projects/:team_id/cohorts/${COHORT_ID}/`]: { id: COHORT_ID, is_static: true, population },
        },
    })
    return <CohortPopulationBanner cohort={{ id: COHORT_ID, is_static: true, population } as CohortType} />
}

type Story = StoryObj<typeof Banner>

export const Running: Story = {
    render: () => <Banner population={BASE_POPULATION} />,
}

export const RetryScheduled: Story = {
    render: () => (
        <Banner
            population={{
                ...BASE_POPULATION,
                status: 'retry_scheduled',
                error_message: 'The system was busy when this cohort was scheduled to calculate.',
                attempts: 2,
                next_attempt_at: '2026-09-07T10:15:00Z',
            }}
        />
    ),
}

export const Failed: Story = {
    render: () => (
        <Banner
            population={{
                ...BASE_POPULATION,
                status: 'failed',
                error_message: 'The system was busy when this cohort was scheduled to calculate.',
                attempts: 6,
                available_actions: ['retry'],
                finished_at: '2026-09-07T10:30:00Z',
            }}
        />
    ),
}

export const InputNoLongerStored: Story = {
    render: () => (
        <Banner
            population={{
                ...BASE_POPULATION,
                status: 'failed',
                error_message: "The people list for this import is no longer stored, so it can't be resumed.",
                input_available: false,
                available_actions: ['reupload'],
                finished_at: '2026-09-07T10:30:00Z',
            }}
        />
    ),
}

export const Abandoned: Story = {
    render: () => (
        <Banner
            population={{
                ...BASE_POPULATION,
                status: 'abandoned',
                available_actions: [],
                finished_at: '2026-09-07T10:30:00Z',
            }}
        />
    ),
}
