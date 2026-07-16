import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { DashboardRefreshStatusText } from './DashboardReloadAction'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'

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
    it.each([
        {
            scenario: 'an initial dashboard request has no cached data',
            dashboard: null,
            action: DashboardLoadAction.InitialLoad,
            dashboardLoading: true,
            expectedLoadingText: 'Loading...',
        },
        {
            scenario: 'an initial dashboard request has cached data',
            dashboard: { id: 5 },
            action: DashboardLoadAction.InitialLoad,
            dashboardLoading: true,
            expectedLoadingText: null,
        },
        {
            scenario: 'a visible dashboard is manually refreshing',
            dashboard: { id: 5 },
            action: DashboardLoadAction.Update,
            dashboardLoading: false,
            expectedLoadingText: 'Refreshing...',
        },
    ])(
        'shows the appropriate status when $scenario',
        ({ dashboard, action, dashboardLoading, expectedLoadingText }) => {
            mockedUseValues.mockImplementation((logic) => {
                if (logic === dashboardLogic) {
                    return {
                        dashboard,
                        dashboardLoading,
                        dashboardStreaming: false,
                        itemsLoading: true,
                        refreshMetrics: { completed: 0, total: 0 },
                        dashboardLoadData: { action },
                        effectiveLastRefresh: null,
                    }
                }
                return {}
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
