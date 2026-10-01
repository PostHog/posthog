import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor } from '@testing-library/dom'

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
export const LastHour: Story = {
    args: {
        periods: [
            {
                key: 'current',
                label: 'Selected period',
                points: OFFLINE_STORY_POINTS.map((point, index) => ({
                    ...point,
                    experiment: {
                        ...point.experiment,
                        started_at: `2026-01-08T10:${String(index * 8).padStart(2, '0')}:00Z`,
                    },
                })),
                dateFrom: '2026-01-08T10:00:00Z',
                dateTo: '2026-01-08T11:00:00Z',
            },
        ],
    },
}
export const LastHourComparison: Story = {
    args: {
        periods: [
            ...LastHour.args!.periods!,
            {
                key: 'previous',
                label: 'Previous period',
                points: LastHour.args!.periods![0].points.map((point) => ({
                    ...point,
                    experiment: {
                        ...point.experiment,
                        started_at: point.experiment.started_at.replace('T10:', 'T09:'),
                    },
                })),
                dateFrom: '2026-01-08T09:00:00Z',
                dateTo: '2026-01-08T10:00:00Z',
            },
        ],
    },
}
export const HiddenSeries: Story = {
    ...LastHourComparison,
    play: async ({ canvasElement }) => {
        const paths = (): NodeListOf<SVGPathElement> =>
            canvasElement.querySelectorAll('[data-attr="offline-score-lines"] path')
        await waitFor(() => {
            if (paths().length !== 2 || Array.from(paths()).some((path) => !path.getAttribute('d'))) {
                throw new Error('Both score lines must finish rendering')
            }
        })
        const legend = canvasElement.querySelector<HTMLButtonElement>('[data-attr="hog-chart-scatter-legend"] button')!
        fireEvent.click(legend)
        await waitFor(() => {
            const visiblePath = paths()[0]?.getAttribute('d')
            if (paths().length !== 1 || !visiblePath || /NaN|Infinity/.test(visiblePath)) {
                throw new Error('Only the visible series must have a valid score line')
            }
        })
    },
}
export const MultipleYears: Story = {
    args: {
        periods: [
            {
                key: 'current',
                label: 'Selected period',
                points: OFFLINE_STORY_POINTS.map((point, index) => ({
                    ...point,
                    experiment: {
                        ...point.experiment,
                        started_at: `${2024 + Math.floor(index / 4)}-${String((index % 4) * 3 + 1).padStart(2, '0')}-08T10:00:00Z`,
                    },
                })),
                dateFrom: '2024-01-01T00:00:00Z',
                dateTo: '2026-01-01T00:00:00Z',
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
