import type { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import { Stage, playHoverAtFraction } from '@posthog/quill-charts/story-helpers'

import { useChartTheme } from 'lib/charts/hooks'

import { VariantTimeseriesTooltip } from './VariantTimeseriesTooltip'

const DAYS = ['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05']
const DELTAS = [0.012, 0.028, 0.041, 0.06, 0.06]
const LOWER = [-0.004, 0.008, 0.019, 0.032, 0.032]
const UPPER = [0.028, 0.048, 0.063, 0.088, 0.088]
const COMPUTED_AT = '2026-06-05T09:30:00Z'
const VARIANT_COLOR = '#1d4aff'

/** Hovering the last day exercises the pending-data footer; any earlier day is a measured day. */
function TooltipChart({
    hasRealData,
    significant,
    isRatioMetric = false,
}: {
    hasRealData: boolean
    significant: boolean
    isRatioMetric?: boolean
}): JSX.Element {
    const theme = useChartTheme()
    return (
        <Stage width={620}>
            <TimeSeriesLineChart
                series={[{ key: 'delta', label: 'Delta', data: DELTAS, color: VARIANT_COLOR, points: { radius: 3 } }]}
                labels={DAYS}
                theme={theme}
                config={{
                    xAxis: { timezone: 'UTC', interval: 'day' },
                    yAxis: { format: 'percentage_scaled', decimalPlaces: 0 },
                    confidenceIntervals: [{ seriesKey: 'delta', lower: LOWER, upper: UPPER }],
                }}
                tooltip={({ dataIndex }) => (
                    <VariantTimeseriesTooltip
                        date={DAYS[dataIndex]}
                        delta={DELTAS[dataIndex]}
                        lowerBound={LOWER[dataIndex]}
                        upperBound={UPPER[dataIndex]}
                        isRatioMetric={isRatioMetric}
                        exposures={2400}
                        denominator={18200}
                        significant={significant}
                        hasRealData={hasRealData}
                        computedAt={COMPUTED_AT}
                        color={VARIANT_COLOR}
                    />
                )}
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
    render: () => <TooltipChart hasRealData significant />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

// A non-significant day — "No" drops the success color so it reads as neutral.
export const NotSignificant: Story = {
    render: () => <TooltipChart hasRealData significant={false} />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

// A day the daily job hasn't computed: adds the pending footer. Hovered mid-plot like the
// others rather than at the trailing point, because a cursor-anchored tooltip near the right
// edge clips out of the snapshot.
export const PendingDay: Story = {
    render: () => <TooltipChart hasRealData={false} significant />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}

// A ratio metric swaps the exposures row for the denominator.
export const RatioMetric: Story = {
    render: () => <TooltipChart hasRealData significant isRatioMetric />,
    play: async ({ canvasElement }) => await playHoverAtFraction(canvasElement, 0.4),
}
