import type { Meta, StoryObj } from '@storybook/react'

import { ModelDownstreamSummary } from './ModelDownstreamSummary'

const meta: Meta<typeof ModelDownstreamSummary> = {
    title: 'Products/Data modeling/Model downstream summary',
    component: ModelDownstreamSummary,
    decorators: [
        (Story) => (
            <dl className="text-sm">
                <Story />
            </dl>
        ),
    ],
    args: { downstreamCount: 3, lineageUrl: '#lineage' },
    parameters: { testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ModelDownstreamSummary>
export const Default: Story = {}
export const OneDependentModel: Story = { args: { downstreamCount: 1 } }
export const NoDependentModels: Story = { args: { downstreamCount: 0 } }
export const Loading: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    args: { loading: true },
}
