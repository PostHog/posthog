import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

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
        agent_context: 'Data Catalog metric: activation_rate',
        dashboard_tiles: [],
        last_modified_at: '2022-04-01T12:24:36',
    },
    layouts: {},
    color: null,
} as DashboardTile

describe('DashboardTextItem', () => {
    beforeEach(() => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: true,
        })
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

    it('does not include agent context in the tile menu', async () => {
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

        expect(screen.queryByText('Agent context')).not.toBeInTheDocument()
        expect(screen.getByText('Human-readable summary')).toBeInTheDocument()
    })
})
