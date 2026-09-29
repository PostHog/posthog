import type { Meta, StoryObj } from '@storybook/react'

import { OfflineScoreTrendChart } from './OfflineScoreTrendChart'
import { OFFLINE_STORY_POINTS, makeOfflineHistoryPoint } from './offlineScoreTrends.fixtures'

const meta: Meta<typeof OfflineScoreTrendChart> = {
    title: 'AI observability/Offline experiments/Score trends',
    component: OfflineScoreTrendChart,
    parameters: { layout: 'padded' },
    args: {
        periods: [
            {
                key: 'current',
                label: 'Selected period',
                points: OFFLINE_STORY_POINTS,
                dateFrom: '2026-01-01T00:00:00Z',
                dateTo: '2026-01-10T00:00:00Z',
            },
        ],
    },
}
export default meta
type Story = StoryObj<typeof OfflineScoreTrendChart>
export const Numeric: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const ComparedPeriods: Story = {
    args: {
        periods: [
            ...meta.args!.periods!,
            {
                key: 'previous',
                label: 'Previous period',
                points: OFFLINE_STORY_POINTS.map((point) => ({
                    ...point,
                    experiment: {
                        ...point.experiment,
                        started_at: point.experiment.started_at.replace('2026-01', '2025-12'),
                    },
                })),
                dateFrom: '2025-12-01T00:00:00Z',
                dateTo: '2025-12-10T00:00:00Z',
            },
        ],
    },
}
export const Categorical: Story = {
    args: {
        periods: [
            {
                key: 'current',
                label: 'Selected period',
                points: OFFLINE_STORY_POINTS.map((point, index) => ({
                    ...point,
                    summary: {
                        ...point.summary,
                        scorer: {
                            ...point.summary.scorer,
                            kind: 'categorical',
                            config: {
                                options: [
                                    { key: 'clear', label: 'Clear' },
                                    { key: 'complete', label: 'Complete' },
                                ],
                                selection_mode: 'multiple',
                            },
                        },
                        mean: null,
                        categories: [
                            { key: 'clear', label: 'Clear', count: 60 + index, rate: (60 + index) / 92 },
                            { key: 'complete', label: 'Complete', count: 70 - index, rate: (70 - index) / 92 },
                        ],
                    },
                })),
            },
        ],
    },
}
export const MissingSuccessfulResults: Story = {
    args: { periods: [{ key: 'current', label: 'Selected period', points: [makeOfflineHistoryPoint(1, null)] }] },
}
