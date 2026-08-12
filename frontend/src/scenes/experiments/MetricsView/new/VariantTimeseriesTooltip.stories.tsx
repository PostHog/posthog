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

/** The last day carries the previous value forward, so the line dashes into it. */
function buildChartData({
    significant,
    lastDayPending,
}: {
    significant: boolean
    lastDayPending: boolean
}): ProcessedChartData {
    const processedData: ProcessedTimeseriesDataPoint[] = DAYS.map((date, i) => ({
        date,
        value: DELTAS[i],
        lower_bound: LOWER[i],
        upper_bound: UPPER[i],
        hasRealData: !(lastDayPending && i === DAYS.length - 1),
        number_of_samples: 1200 + i * 300,
        denominator_sum: 18200 + i * 900,
        significant,
    }))
    return {
        labels: DAYS,
        processedData,
        computedAt: COMPUTED_AT,
        variantColor: '#1d4aff',
    }
}

/** Renders the real chart, so these snapshots cover its axis and CI band, not just the tooltip. */
function TooltipChart({
    significant = true,
    lastDayPending = false,
    isRatioMetric = false,
}: {
    significant?: boolean
    lastDayPending?: boolean
    isRatioMetric?: boolean
}): JSX.Element {
    return (
        <Stage width={620}>
            <VariantTimeseriesChart
                chartData={buildChartData({ significant, lastDayPending })}
                isRatioMetric={isRatioMetric}
            />
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

// A measured, significant day: delta, interval, exposures, and the calculated-at block.
export const SignificantDay: Story = {
    render: () => <TooltipChart />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

// A non-significant day — "No" drops the success color so it reads as neutral.
export const NotSignificant: Story = {
    render: () => <TooltipChart significant={false} />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

// A day the daily job hasn't computed: adds the pending footer, and the line dashes into the
// trailing point. Hovered mid-plot like the others, because a cursor-anchored tooltip near the
// right edge clips out of the snapshot.
export const PendingDay: Story = {
    render: () => <TooltipChart lastDayPending />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

// A ratio metric swaps the exposures row for the denominator.
export const RatioMetric: Story = {
    render: () => <TooltipChart isRatioMetric />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}
