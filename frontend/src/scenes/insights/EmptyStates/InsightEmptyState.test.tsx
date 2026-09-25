import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { InsightEmptyState, StatelessInsightLoadingState } from './EmptyStates'

describe('EmptyStates', () => {
    describe('<InsightEmptyState />', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({
                get: {
                    '/api/projects/:projectId/tasks/': { count: 0, results: [] },
                },
            })
        })

        const mountWithTeam = (overrides: Partial<TeamType>): void => {
            teamLogic.mount()
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ...overrides })
        }

        afterEach(() => {
            cleanup()
        })

        it.each([
            {
                name: 'sample data before any events were ingested',
                team: { ingested_event: false, is_demo: false },
                props: {},
                expectSampleData: true,
            },
            {
                name: 'the regular empty state once events were ingested',
                team: { ingested_event: true, is_demo: false },
                props: {},
                expectSampleData: false,
            },
            {
                name: 'the regular empty state in demo projects',
                team: { ingested_event: false, is_demo: true },
                props: {},
                expectSampleData: false,
            },
            {
                name: 'custom copy over sample data when no variant was passed',
                team: { ingested_event: false, is_demo: false },
                props: { heading: 'No revenue data' },
                expectSampleData: false,
            },
            {
                name: 'sample data over custom copy when a variant explicitly opted in',
                team: { ingested_event: false, is_demo: false },
                props: { heading: 'No rows', sampleDataVariant: 'table' as const },
                expectSampleData: true,
            },
            {
                name: 'the regular empty state when the call site opted out',
                team: { ingested_event: false, is_demo: false },
                props: { sampleDataVariant: null },
                expectSampleData: false,
            },
        ])('renders $name', ({ team, props, expectSampleData }) => {
            mountWithTeam(team)
            const { container } = render(<InsightEmptyState {...props} />)

            expect(!!container.querySelector('[data-attr="insight-sample-data-state"]')).toBe(expectSampleData)
            expect(!!container.querySelector('[data-attr="insight-empty-state"]')).toBe(!expectSampleData)
        })
    })

    describe('<StatelessInsightLoadingState />', () => {
        beforeEach(() => {
            initKeaTests()
            userLogic.mount()
        })

        afterEach(() => {
            cleanup()
        })

        const POLL_RESPONSE = {
            status: {
                query_progress: {
                    rows_read: 5000,
                    bytes_read: 100000,
                    estimated_rows_total: 10000,
                    active_cpu_time: 1000000,
                    time_elapsed: 1000,
                },
                start_time: '2026-01-01T00:00:00Z',
            },
            previousStatus: { query_progress: { rows_read: 4000, bytes_read: 90000 } },
        } as any

        it.each([
            { name: 'hides', isStaff: false, expectVisible: false },
            { name: 'shows', isStaff: true, expectVisible: true },
        ])('$name query internals while loading when is_staff is $isStaff', ({ isStaff, expectVisible }) => {
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

            const { container } = render(
                <StatelessInsightLoadingState
                    queryId="01234567-89ab-cdef-0123-456789abcdef"
                    pollResponse={POLL_RESPONSE}
                />
            )

            expect(container.textContent).toContain('insights')
            expect(container.textContent?.includes('01234567-89ab-cdef-0123-456789abcdef')).toBe(expectVisible)
            expect(container.textContent?.includes('CPU')).toBe(expectVisible)
        })
    })
})
