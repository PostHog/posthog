import type { Meta, StoryObj } from '@storybook/react'

import { ModelViewSummary } from './ModelViewSummary'

const meta: Meta<typeof ModelViewSummary> = {
    title: 'Products/Data modeling/Model view summary',
    component: ModelViewSummary,
    args: { downstreamCount: 3, lineageUrl: '#lineage' },
    parameters: { testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ModelViewSummary>
export const Default: Story = {}
export const OneDependentModel: Story = { args: { downstreamCount: 1 } }
export const NoDependentModels: Story = { args: { downstreamCount: 0 } }
