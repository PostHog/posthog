import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { errorTrackingQuery } from '@posthog/products-error-tracking/frontend/queries'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { teamLogic } from 'scenes/teamLogic'
import { ErrorTrackingTile, TileId } from 'scenes/web-analytics/common'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, TeamType } from '~/types'

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
        useMocks({
            post: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    const mountWithSetupStatus = (team: Partial<TeamType>, hasIssues: boolean): void => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ...team })
        const setupStatus = productSetupStatusLogic({ productKey: ProductKey.ERROR_TRACKING })
        setupStatus.mount()
        setupStatus.actions.setDetectedStatus(hasIssues ? 'has-data' : 'needs-setup')
    }

    it('reads an empty table as good news when exceptions reach the project', async () => {
        mountWithSetupStatus({ autocapture_exceptions_opt_in: false }, true)
        render(<WebAnalyticsErrorTrackingTile tile={tile} />)

        await waitFor(() => expect(screen.getByText('No errors found!')).toBeInTheDocument())
    })

    it('reads an empty table as good news when exception autocapture is on but nothing has errored yet', async () => {
        mountWithSetupStatus({ autocapture_exceptions_opt_in: true }, false)
        render(<WebAnalyticsErrorTrackingTile tile={tile} />)

        await waitFor(() => expect(screen.getByText('No errors found!')).toBeInTheDocument())
    })

    it('keeps the generic copy when nothing reports errors, so a missing SDK is not read as no errors', async () => {
        mountWithSetupStatus({ autocapture_exceptions_opt_in: false }, false)
        render(<WebAnalyticsErrorTrackingTile tile={tile} />)

        await waitFor(() => expect(screen.getByText('There are no matching events for this query')).toBeInTheDocument())
        expect(screen.queryByText('No errors found!')).not.toBeInTheDocument()
    })
})
