import type { Meta, StoryObj } from '@storybook/react'

import { OpenDashboardLink } from './OpenDashboardLink'

const meta: Meta<typeof OpenDashboardLink> = {
    title: 'Scenes-App/AI observability/Home/Open dashboard link',
    component: OpenDashboardLink,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { dashboardId: 42 },
}
export default meta

type Story = StoryObj<typeof OpenDashboardLink>

export const WithDashboard: Story = {}

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-40">
                <StoryComponent />
            </div>
        ),
    ],
}

export const NoDashboard: Story = { args: { dashboardId: null } }
