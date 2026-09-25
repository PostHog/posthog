import type { Meta, StoryObj } from '@storybook/react'

import { resolveSaveCandidates, SaveTargetCycler } from './SaveTargetCycler'

const QUERY = `WITH sample AS (
    SELECT event, timestamp FROM events LIMIT 100
)
SELECT event, count() FROM sample GROUP BY event`

const meta: Meta<typeof SaveTargetCycler> = {
    title: 'Scenes-App/Data Warehouse/SaveTargetCycler',
    component: SaveTargetCycler,
    args: { onChange: () => {} },
    decorators: [
        (Story) => (
            <div className="w-[36rem] p-4">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SaveTargetCycler>

export const StraySelection: Story = {
    args: { candidates: resolveSaveCandidates(QUERY, 20, 'sa') },
}

export const DeliberateSelection: Story = {
    args: { candidates: resolveSaveCandidates(QUERY, 20, 'SELECT event, timestamp FROM events LIMIT 100') },
}

export const NoSelection: Story = {
    args: { candidates: resolveSaveCandidates(QUERY, 20, null) },
}
