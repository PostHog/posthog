import { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions, useMountedLogic } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import dashboardFixture from 'scenes/dashboard/__mocks__/dashboard.json'
import { DashboardInsightColorsModal } from 'scenes/dashboard/DashboardInsightColorsModal'
import { dashboardInsightColorsModalLogic } from 'scenes/dashboard/dashboardInsightColorsModalLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { DashboardType, QueryBasedInsightModel } from '~/types'

const DASHBOARD_ID = 5

const dashboard = {
    ...dashboardFixture,
    id: DASHBOARD_ID,
    tiles: dashboardFixture.tiles.map((tile, index) => ({ ...tile, id: index + 1 })),
} as unknown as DashboardType<QueryBasedInsightModel>

const meta: Meta = {
    title: 'Scenes/Dashboards/Customize breakdown colors',
    component: DashboardInsightColorsModal,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2023-07-01',
    },
    render: () => (
        <BindLogic logic={dashboardLogic} props={{ id: DASHBOARD_ID }}>
            <StoryCanvas />
        </BindLogic>
    ),
}

function StoryCanvas(): JSX.Element {
    useMountedLogic(dashboardLogic)
    useMountedLogic(dashboardInsightColorsModalLogic)
    const { showInsightColorsModal } = useActions(dashboardInsightColorsModalLogic)

    useStorybookMocks({
        get: {
            [`/api/environments/:team_id/dashboards/${DASHBOARD_ID}/`]: dashboard,
        },
    })

    useOnMountEffect(() => {
        showInsightColorsModal(DASHBOARD_ID)
    })

    return <DashboardInsightColorsModal />
}

export default meta
type Story = StoryObj

export const CustomizeBreakdownColors: Story = {}
