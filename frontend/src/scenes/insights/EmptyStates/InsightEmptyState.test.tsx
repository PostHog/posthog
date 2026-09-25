import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { InsightEmptyState } from './EmptyStates'

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

        it.each([
            { name: 'nothing extra when the query was quick', queryElapsedMs: 3_000, expectNote: false },
            { name: 'nothing extra just below the slow threshold', queryElapsedMs: 14_500, expectNote: false },
            { name: 'how long the query ran when it crawled', queryElapsedMs: 42_000, expectNote: true },
        ])('shows $name', ({ queryElapsedMs, expectNote }) => {
            mountWithTeam({ ingested_event: true, is_demo: false })
            render(<InsightEmptyState queryElapsedMs={queryElapsedMs} onRetry={() => {}} />)

            expect(!!screen.queryByText(/seconds to come back empty/)).toBe(expectNote)
            expect(!!screen.queryByText('Run again')).toBe(expectNote)
        })

        it('re-runs the query from the slow empty state', async () => {
            mountWithTeam({ ingested_event: true, is_demo: false })
            const onRetry = jest.fn()
            const { rerender } = render(<InsightEmptyState queryElapsedMs={42_000} onRetry={onRetry} />)

            await userEvent.click(screen.getByText('Run again'))
            await userEvent.click(screen.getByText('Run again'))

            expect(onRetry).toHaveBeenCalledTimes(1)

            rerender(<InsightEmptyState queryElapsedMs={38_000} onRetry={onRetry} />)
            await userEvent.click(screen.getByText('Run again'))

            expect(onRetry).toHaveBeenCalledTimes(2)
        })
    })
})
