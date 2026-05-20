import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { ProductIntroduction } from '../ProductIntroduction/ProductIntroduction'
import { MCPUseCaseCard } from './MCPUseCaseCard'

const meta: Meta<typeof MCPUseCaseCard> = {
    title: 'Components/MCP Use Case Card',
    component: MCPUseCaseCard,
    parameters: {
        layout: 'centered',
        featureFlags: [FEATURE_FLAGS.MCP_HINTS],
    },
}
export default meta

type Story = StoryObj<typeof MCPUseCaseCard>

export const FeatureFlagsCreate: Story = {
    args: { surfaceKey: 'feature_flags.create' },
}

export const DashboardsCreate: Story = {
    args: { surfaceKey: 'dashboards.create' },
}

export const ExperimentsCreate: Story = {
    args: { surfaceKey: 'experiments.create' },
}

export const SurveysCreate: Story = {
    args: { surfaceKey: 'surveys.create' },
}

export const InsightsCreate: Story = {
    args: { surfaceKey: 'insights.create' },
}

// Composite: the card as it actually appears inside a ProductIntroduction empty state.
export const InsideProductIntroduction: Story = {
    parameters: { layout: 'padded' },
    render: () => (
        <ProductIntroduction
            productName="Feature flags"
            productKey={ProductKey.FEATURE_FLAGS}
            thingName="feature flag"
            description="Use feature flags to safely deploy and roll back new features in an easy-to-manage way."
            docsURL="https://posthog.com/docs/feature-flags/manual"
            action={() => undefined}
            isEmpty={true}
            mcpSurfaceKey="feature_flags.create"
        />
    ),
}
