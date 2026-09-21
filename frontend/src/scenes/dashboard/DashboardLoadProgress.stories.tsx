import { Meta, StoryObj } from '@storybook/react'

import { DashboardLoadProgress, DashboardLoadProgressProps } from './DashboardLoadProgress'

const meta: Meta<DashboardLoadProgressProps> = {
    title: 'Scenes-App/Dashboards/Dashboard load progress',
    component: DashboardLoadProgress,
    args: {
        completed: 4,
        total: 19,
    },
    tags: ['autodocs'],
}
type Story = StoryObj<DashboardLoadProgressProps>
export default meta

export const Default: Story = {}

export const AlmostDone: Story = {
    args: {
        completed: 18,
        total: 19,
    },
}
