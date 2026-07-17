import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'
import { DashboardPlacement, DashboardType, QueryBasedInsightModel } from '~/types'

import {
    DashboardAutoRefreshRestrictionBanner,
    DashboardAutoRefreshRestrictionNotice,
} from './DashboardAutoRefreshRestrictionBanner'

describe('DashboardAutoRefreshRestrictionBanner', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => cleanup())

    it.each([DashboardPlacement.Public, DashboardPlacement.Export])(
        'does not mount sharing state for %s placement',
        (placement) => {
            const { container } = render(<DashboardAutoRefreshRestrictionBanner placement={placement} />)

            expect(container).toBeEmptyDOMElement()
        }
    )

    it('shows an action to shorten the dashboard date range', () => {
        const dashboard = {
            id: 1,
            name: 'Dashboard',
            filters: { date_from: '-90d' },
            tiles: [],
        } as unknown as DashboardType<QueryBasedInsightModel>

        const dashboardsLogic = dashboardsModel()
        dashboardsLogic.mount()
        const updateDashboard = jest.spyOn(dashboardsLogic.actions, 'updateDashboard')

        render(
            <DashboardAutoRefreshRestrictionNotice
                dashboard={dashboard}
                restriction={{ source: 'dashboard' }}
                canEdit
            />
        )

        expect(
            screen.getByText(
                'Auto refresh is disabled because querying more than 30 days of data is too expensive. Set the dashboard to the last 7 days to enable it.'
            )
        ).toBeInTheDocument()
        const actionLabels = screen.getAllByText('Set to last 7 days')
        expect(actionLabels).not.toHaveLength(0)

        fireEvent.click(actionLabels[0])
        expect(updateDashboard).toHaveBeenCalledWith({
            id: dashboard.id,
            filters: { date_from: '-7d', date_to: null, explicitDate: false },
        })

        dashboardsLogic.unmount()
    })

    it('can be dismissed', () => {
        const dashboard = {
            id: 1,
            name: 'Dashboard',
            filters: { date_from: '-90d' },
            tiles: [],
        } as unknown as DashboardType<QueryBasedInsightModel>

        const { getByLabelText, queryByText } = render(
            <DashboardAutoRefreshRestrictionNotice
                dashboard={dashboard}
                restriction={{ source: 'dashboard' }}
                canEdit={false}
            />
        )

        fireEvent.click(getByLabelText('close'))

        expect(queryByText(/Auto refresh is disabled/)).not.toBeInTheDocument()
    })
})
