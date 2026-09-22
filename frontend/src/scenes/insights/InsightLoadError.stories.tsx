import { Meta, StoryObj } from '@storybook/react'

import { InsightLoadError } from 'scenes/insights/InsightLoadError'

const meta: Meta<typeof InsightLoadError> = {
    title: 'Scenes-App/Insights/InsightLoadError',
    component: InsightLoadError,
    args: { status: 500, onRetry: () => {} },
}
export default meta

type Story = StoryObj<typeof InsightLoadError>

export const ServerError: Story = {}

export const NoResponse: Story = { args: { status: null } }
