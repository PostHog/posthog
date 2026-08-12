import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { dayjs } from 'lib/dayjs'

import { type SparklineData } from './hogInvocationsLogic'
import { InvocationsSparkline } from './InvocationsSparkline'

const meta: Meta<typeof InvocationsSparkline> = {
    title: 'Scenes-App/HogFunctions/InvocationsSparkline',
    component: InvocationsSparkline,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof InvocationsSparkline>

/** Hourly buckets on a fixed anchor so the bars and axis ticks are identical across snapshot runs. */
function exampleData(bucketCount = 48): SparklineData {
    const start = dayjs('2026-06-01T00:00:00Z')
    const dates = Array.from({ length: bucketCount }, (_, i) => start.add(i, 'hour').toISOString())
    const wave = (i: number, phase: number, scale: number): number =>
        Math.max(0, Math.round(scale * (1 + Math.sin(i / 5 + phase))))
    return {
        dates,
        series: [
            { name: 'failed', color: 'danger', values: dates.map((_, i) => (i % 7 === 0 ? wave(i, 1, 6) : 0)) },
            { name: 'running', color: 'warning', values: dates.map((_, i) => wave(i, 2, 4)) },
            { name: 'succeeded', color: 'success', values: dates.map((_, i) => wave(i, 0, 40)) },
        ],
    }
}

function Stage({ children }: { children: ReactNode }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ width: 760 }}>{children}</div>
}

/** Stacked succeeded/running/failed buckets — the default state above the runs table. */
export const WithActivity: Story = {
    render: () => (
        <Stage>
            <InvocationsSparkline data={exampleData()} loading={false} onDateRangeChange={() => {}} />
        </Stage>
    ),
}

/** Every bucket empty: the chart is replaced by copy rather than an axis with no bars. */
export const NoInvocations: Story = {
    render: () => {
        const { dates, series } = exampleData(12)
        return (
            <Stage>
                <InvocationsSparkline
                    data={{ dates, series: series.map((s) => ({ ...s, values: s.values.map(() => 0) })) }}
                    loading={false}
                    onDateRangeChange={() => {}}
                />
            </Stage>
        )
    },
}

/** A minute-bucketed window, which switches the x-axis ticks from hours to minutes. */
export const MinuteBuckets: Story = {
    render: () => {
        const start = dayjs('2026-06-01T00:00:00Z')
        const dates = Array.from({ length: 60 }, (_, i) => start.add(i, 'minute').toISOString())
        return (
            <Stage>
                <InvocationsSparkline
                    data={{
                        dates,
                        series: [
                            {
                                name: 'succeeded',
                                color: 'success',
                                values: dates.map((_, i) => Math.max(0, Math.round(12 * (1 + Math.sin(i / 4))))),
                            },
                        ],
                    }}
                    loading={false}
                    onDateRangeChange={() => {}}
                />
            </Stage>
        )
    },
}
