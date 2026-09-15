import type { Meta, StoryObj } from '@storybook/react'

import { ModelViewSummary } from './ModelViewSummary'

const meta: Meta<typeof ModelViewSummary> = {
    title: 'Products/Data modeling/Model view summary',
    component: ModelViewSummary,
    decorators: [
        (Story) => (
            // The card is width-filling by design, so a story needs a definite column to sit in:
            // Storybook's padded root is shrink-to-fit and collapses it to nothing otherwise.
            <div className="w-[56rem]">
                <Story />
            </div>
        ),
    ],
    args: { downstreamCount: 3, lineageUrl: '#lineage' },
    parameters: { testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ModelViewSummary>
export const Default: Story = {}
export const OneDependentModel: Story = { args: { downstreamCount: 1 } }
export const NoDependentModels: Story = { args: { downstreamCount: 0 } }
