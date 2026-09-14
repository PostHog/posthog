import type { Meta, StoryObj } from '@storybook/react'

import { ModelMetadata } from './ModelMetadata'
import { ModelSummaryCard } from './ModelSummaryCard'

const meta: Meta<typeof ModelSummaryCard> = {
    title: 'Products/Data modeling/Model summary card',
    component: ModelSummaryCard,
    args: {
        dataAttr: 'model-summary-card-story',
        children: <span className="font-semibold">Runs on demand</span>,
        metadata: <ModelMetadata createdAt="2026-01-10T10:00:00Z" />,
    },
    parameters: { mockDate: '2026-09-14', testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ModelSummaryCard>
export const Default: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-128 max-w-full">
                <Story />
            </div>
        ),
    ],
}
