import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'

import { initKeaTests } from '~/test/init'
import { DashboardPlacement, DashboardTile } from '~/types'

import { DashboardTextItem } from './DashboardTextItem'

const tile = {
    id: 1,
    text: {
        id: 10,
        body: 'Human-readable summary',
        agent_context: 'Semantic layer metric: activation_rate',
        dashboard_tiles: [],
        last_modified_at: '2022-04-01T12:24:36',
    },
    layouts: {},
    color: null,
} as DashboardTile

describe('DashboardTextItem', () => {
    beforeEach(() => {
        initKeaTests()
        dashboardWidgetMenusLogic({
            instanceKey: 'text-10',
            dashboardId: 99,
            dashboards: undefined,
            dashboard_tiles: [],
        }).mount()
    })

    afterEach(() => {
        cleanup()
        dashboardWidgetMenusLogic({
            instanceKey: 'text-10',
            dashboardId: 99,
            dashboards: undefined,
            dashboard_tiles: [],
        }).unmount()
    })

    it('shows agent context from the tile menu', async () => {
        render(
            <DashboardTextItem
                tile={tile}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                onEdit={jest.fn()}
                onDuplicate={jest.fn()}
                showEditingControls
            />
        )

        expect(screen.getByText('Human-readable summary')).toBeInTheDocument()
        expect(screen.queryByText('Agent context')).not.toBeInTheDocument()

        await userEvent.click(screen.getByLabelText('more'))
        await userEvent.click(screen.getByText('Agent context'))

        expect(screen.getByText('Semantic layer metric: activation_rate')).toBeInTheDocument()
        expect(screen.queryByText('Human-readable summary')).not.toBeInTheDocument()
    })
})
