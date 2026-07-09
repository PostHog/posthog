import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { isValidElement } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { InsightEmptyState, renderDetailWithLinks } from './EmptyStates'

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

    describe('renderDetailWithLinks', () => {
        const linkedUrls = (detail: string): string[] =>
            renderDetailWithLinks(detail)
                .filter((part): part is JSX.Element => isValidElement(part))
                .map((el) => (el.props as { to: string }).to)

        it.each([
            ['links a PostHog docs URL', 'see https://posthog.com/docs/x for help', ['https://posthog.com/docs/x']],
            ['links a PostHog subdomain URL', 'visit https://eu.posthog.com/foo now', ['https://eu.posthog.com/foo']],
            ['leaves an external URL as plain text', 'go to https://evil.example.com/phish', []],
            ['leaves a lookalike host as plain text', 'open https://posthog.com.evil.com/x here', []],
            ['renders plain detail with no links', 'This query ran out of memory.', []],
        ])('%s', (_name, detail, expected) => {
            expect(linkedUrls(detail)).toEqual(expected)
        })
    })
})
