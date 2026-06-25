import { Meta, StoryObj } from '@storybook/react'

import { MCPUseCaseCard } from './MCPUseCaseCard'

const meta: Meta<typeof MCPUseCaseCard> = {
    title: 'Components/MCP Use Case Card',
    component: MCPUseCaseCard,
    parameters: {
        layout: 'centered',
    },
}
export default meta

type Story = StoryObj<typeof MCPUseCaseCard>

export const FeatureFlagsCreate: Story = {
    args: { surfaceKey: 'feature_flags.create', forceDisplay: true },
}

export const DashboardsCreate: Story = {
    args: { surfaceKey: 'dashboards.create', forceDisplay: true },
}

export const ExperimentsCreate: Story = {
    args: { surfaceKey: 'experiments.create', forceDisplay: true },
}

export const SurveysCreate: Story = {
    args: { surfaceKey: 'surveys.create', forceDisplay: true },
}

export const InsightsCreate: Story = {
    args: { surfaceKey: 'insights.create', forceDisplay: true },
}
