import type { Meta, StoryObj } from '@storybook/react'

import { detailSummaries } from './offlineDetailFixtures'
import { OfflineScoreSummaryDisplay } from './OfflineScoreSummaryDisplay'

const meta: Meta<typeof OfflineScoreSummaryDisplay> = {
    title: 'AI observability/Offline experiments/Score summary',
    component: OfflineScoreSummaryDisplay,
    parameters: { layout: 'padded' },
    args: { summary: detailSummaries[0] },
}
export default meta
type Story = StoryObj<typeof OfflineScoreSummaryDisplay>

export const Numeric: Story = {}
export const Boolean: Story = { args: { summary: detailSummaries[1] } }
export const Unconfigured: Story = {
    args: {
        summary: {
            ...detailSummaries[0],
            scorer: { ...detailSummaries[0].scorer, config: {} },
            pass_count: null,
            fail_count: null,
            pass_rate: null,
        },
    },
}
