import type { Meta, StoryObj } from '@storybook/react'

import { Stage, playHoverAtFraction } from '@posthog/quill-charts/story-helpers'

import type { ProcessedChartData, ProcessedTimeseriesDataPoint } from '../../experimentTimeseriesLogic'
import { VariantTimeseriesChart } from './VariantTimeseriesChart'
import { VariantTimeseriesTooltip } from './VariantTimeseriesTooltip'

const DAYS = ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05']
const DELTAS = [0.012, 0.028, 0.041, 0.06, 0.06]
const LOWER = [-0.004, 0.008, 0.019, 0.032, 0.032]
const UPPER = [0.028, 0.048, 0.063, 0.088, 0.088]
const COMPUTED_AT = '2026-06-05T09:30:00Z'
const HAS_REAL_DATA_ALL = [true, true, true, true, true]
const HAS_REAL_DATA_PENDING_TAIL = [true, false, false, false, false]

function buildChartData(hasRealData: boolean[]): ProcessedChartData {
    const processedData: ProcessedTimeseriesDataPoint[] = DAYS.map((date, i) => ({
        date,
        value: DELTAS[i],
        lower_bound: LOWER[i],
        upper_bound: UPPER[i],
        hasRealData: hasRealData[i],
        number_of_samples: 1200 + i * 300,
        denominator_sum: 18200 + i * 900,
        significant: true,
    }))
    return {
        labels: DAYS,
        processedData,
        computedAt: COMPUTED_AT,
        variantColor: '#1d4aff',
    }
}

function TooltipChart({ hasRealData = HAS_REAL_DATA_ALL }: { hasRealData?: boolean[] }): JSX.Element {
    return (
        <Stage width={620}>
            <VariantTimeseriesChart chartData={buildChartData(hasRealData)} />
        </Stage>
    )
}

const meta: Meta<typeof VariantTimeseriesTooltip> = {
    title: 'Experiments/VariantTimeseriesTooltip',
    component: VariantTimeseriesTooltip,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof VariantTimeseriesTooltip>

export const SignificantDay: Story = {
    render: () => <TooltipChart />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

export const PendingDay: Story = {
    render: () => <TooltipChart hasRealData={HAS_REAL_DATA_PENDING_TAIL} />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}
