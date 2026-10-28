import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { errorTrackingQuery } from '@posthog/products-error-tracking/frontend/queries'

import { teamLogic } from 'scenes/teamLogic'
import { ErrorTrackingTile, TileId } from 'scenes/web-analytics/common'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import { WebAnalyticsErrorTrackingTile } from './WebAnalyticsErrorTracking'

describe('WebAnalyticsErrorTrackingTile', () => {
    const tile: ErrorTrackingTile = {
        kind: 'error_tracking',
        tileId: TileId.ERROR_TRACKING,
        layout: {},
        query: errorTrackingQuery({
            orderBy: 'users',
            dateRange: { date_from: '-7d', date_to: null },
            filterTestAccounts: false,
            filterGroup: { type: FilterLogicalOperator.And, values: [] },
            columns: ['error', 'users', 'occurrences', 'last_seen'],
            limit: 4,
        }),
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'good news when exceptions already reach the project',
            autocaptureOptIn: false,
            issuesExistResponse: [200, { exists: true }] as [number, object],
            expected: 'No errors found!',
            queryRuns: true,
        },
        {
            name: 'good news when autocapture is on but nothing has errored yet',
            autocaptureOptIn: true,
            issuesExistResponse: [200, { exists: false }] as [number, object],
            expected: 'No errors found!',
            queryRuns: true,
        },
        {
            name: 'an upsell without running the query when nothing reports errors',
            autocaptureOptIn: false,
            issuesExistResponse: [200, { exists: false }] as [number, object],
            expected: 'Error tracking is not set up',
            queryRuns: false,
        },
        {
            name: 'the generic copy when setup detection fails',
            autocaptureOptIn: false,
            issuesExistResponse: [500, {}] as [number, object],
            expected: 'There are no matching events for this query',
            queryRuns: true,
        },
    ])('shows $name', async ({ autocaptureOptIn, issuesExistResponse, expected, queryRuns }) => {
        let queryRequests = 0
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/issues/exists/': issuesExistResponse,
            },
            post: {
                '/api/environments/:team_id/query/:kind/': () => {
                    queryRequests += 1
                    return [200, { results: [] }]
                },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: autocaptureOptIn,
        })
        render(<WebAnalyticsErrorTrackingTile tile={tile} />)

        await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument())
        expect(queryRequests > 0).toBe(queryRuns)
    })
})
