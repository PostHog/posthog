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

export const NearThreshold: Story = {
    args: {
        summary: {
            ...detailSummaries[0],
            mean: 0.9999999,
            scorer: { ...detailSummaries[0].scorer, config: { passing_rule: { operator: 'gte', threshold: 1 } } },
        },
    },
}
export const Categorical: Story = {
    args: {
        summary: {
            ...detailSummaries[0],
            mean: null,
            scorer: {
                ...detailSummaries[0].scorer,
                kind: 'categorical',
                config: {
                    options: [
                        { key: 'good', label: 'Good' },
                        { key: 'bad', label: 'Bad' },
                    ],
                    passing_rule: { categories: ['good'] },
                },
            },
            categories: [
                { key: 'good', label: 'Good', count: 3, rate: 0.75 },
                { key: 'bad', label: 'Bad', count: 1, rate: 0.25 },
            ],
            pass_count: 3,
            fail_count: 1,
            pass_rate: 0.75,
            status_counts: { ok: 4 },
        },
    },
}
