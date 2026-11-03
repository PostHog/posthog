import type { Meta, StoryObj } from '@storybook/react'

import { MetricDescription } from './MetricDescription'

const meta: Meta<typeof MetricDescription> = {
    title: 'Data catalog/Metric description',
    component: MetricDescription,
    parameters: { viewMode: 'story' },
    render: (props) => (
        // A fixed width keeps the clamp point, and so the baseline, the same on every run.
        <div className="w-96 p-4 text-xs text-tertiary">
            <MetricDescription {...props} />
        </div>
    ),
}
export default meta

export const Clamped: StoryObj<typeof MetricDescription> = {
    args: {
        description:
            'The number of dashboards created in PostHog, across every surface that can create one: web, API, MCP, PostHog AI, CLI and Terraform. Each creation counts once, including dashboards made from a template or by duplicating an existing one.',
    },
}
