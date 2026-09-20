import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { errorTrackingQuery } from '@posthog/products-error-tracking/frontend/queries'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { ProductSetupStatus } from 'lib/components/ProductEmptyState/types'
import { teamLogic } from 'scenes/teamLogic'
import { ErrorTrackingTile, TileId } from 'scenes/web-analytics/common'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
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
        useMocks({
            post: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    const mountWithSetupStatus = (
        autocaptureOptIn: boolean,
        setupStatus: ProductSetupStatus | null,
        skipped: boolean = false
    ): void => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: autocaptureOptIn,
        })
        const setup = productSetupStatusLogic({ productKey: ProductKey.ERROR_TRACKING })
        setup.mount()
        if (setupStatus) {
            setup.actions.setDetectedStatus(setupStatus)
        }
        // Set either way: the skip is persisted, so leaving it unset would leak into the next case.
        if (skipped) {
            setup.actions.skipEmptyState()
        } else {
            setup.actions.unskipEmptyState()
        }
    }

    it.each([
        {
            name: 'good news when exceptions already reach the project',
            autocaptureOptIn: false,
            setupStatus: 'has-data' as const,
            expected: 'No errors found!',
        },
        {
            name: 'good news when autocapture is on but nothing has errored yet',
            autocaptureOptIn: true,
            setupStatus: 'needs-setup' as const,
            expected: 'No errors found!',
        },
        {
            name: 'a nudge when nothing reports errors, so a missing SDK does not read as no errors',
            autocaptureOptIn: false,
            setupStatus: 'needs-setup' as const,
            expected: 'Error tracking is not set up',
            expectsSetupButton: true,
        },
        {
            name: 'the generic copy once the setup screen has been dismissed, instead of pitching it again',
            autocaptureOptIn: false,
            setupStatus: 'needs-setup' as const,
            skipped: true,
            expected: 'There are no matching events for this query',
        },
        {
            name: 'the generic copy while setup detection has not answered',
            autocaptureOptIn: false,
            setupStatus: null,
            expected: 'There are no matching events for this query',
        },
    ])(
        'reads an empty table as $name',
        async ({ autocaptureOptIn, setupStatus, skipped, expected, expectsSetupButton }) => {
            mountWithSetupStatus(autocaptureOptIn, setupStatus, skipped)
            render(<WebAnalyticsErrorTrackingTile tile={tile} />)

            await waitFor(() => expect(screen.getByText(expected)).toBeInTheDocument())
            // The button is what costs the reader a trip: it leads back to the scene the setup
            // pitch belongs to, so it must appear only alongside that pitch.
            expect(screen.queryByText('Set up error tracking')).toEqual(expectsSetupButton ? expect.anything() : null)
        }
    )
})
