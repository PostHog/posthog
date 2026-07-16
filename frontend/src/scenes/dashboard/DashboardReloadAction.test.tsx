import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { DashboardLoadAction } from './dashboardLogic'
import { DashboardRefreshStatusText } from './DashboardReloadAction'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('./dashboardLogic', () => ({
    dashboardLogic: { __mock: 'dashboardLogic' },
    DashboardLoadAction: {
        InitialLoad: 'initial_load',
        Update: 'update',
    },
}))

const mockedUseValues = jest.mocked(useValues)

describe('DashboardRefreshStatusText', () => {
    afterEach(cleanup)

    it.each([
        {
            scenario: 'an initial dashboard request has no cached data',
            dashboard: null,
            action: DashboardLoadAction.InitialLoad,
            dashboardLoading: true,
            dashboardRevalidationError: null,
            itemsLoading: true,
            expectedLoadingText: 'Loading...',
        },
        {
            scenario: 'an initial dashboard request has cached data',
            dashboard: { id: 5 },
            action: DashboardLoadAction.InitialLoad,
            dashboardLoading: true,
            dashboardRevalidationError: null,
            itemsLoading: true,
            expectedLoadingText: null,
        },
        {
            scenario: 'a visible dashboard is manually refreshing',
            dashboard: { id: 5 },
            action: DashboardLoadAction.Update,
            dashboardLoading: false,
            dashboardRevalidationError: null,
            itemsLoading: true,
            expectedLoadingText: 'Refreshing...',
        },
        {
            scenario: 'a cached dashboard failed to refresh',
            dashboard: { id: 5 },
            action: DashboardLoadAction.InitialLoad,
            dashboardLoading: false,
            dashboardRevalidationError: 'Network error',
            itemsLoading: false,
            expectedLoadingText: 'Refresh failed',
        },
    ])(
        'shows the appropriate status when $scenario',
        ({ dashboard, action, dashboardLoading, dashboardRevalidationError, itemsLoading, expectedLoadingText }) => {
            mockedUseValues.mockReturnValue({
                dashboard,
                dashboardLoading,
                dashboardStreaming: false,
                dashboardRevalidationError,
                itemsLoading,
                refreshMetrics: { completed: 0, total: 0 },
                dashboardLoadData: { action },
                effectiveLastRefresh: null,
            })

            render(<DashboardRefreshStatusText />)

            if (expectedLoadingText) {
                expect(screen.getByText(expectedLoadingText)).toBeInTheDocument()
            } else {
                expect(screen.queryByText('Loading...')).not.toBeInTheDocument()
            }
        }
    )
})
