import { Meta, StoryObj } from '@storybook/react'

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
    decorators: [
        (Story) => (
            <div className="w-[760px]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof InvocationsSparkline>

/** Anchored to a fixed date so the bars and axis ticks are identical across snapshot runs. */
function exampleData(): SparklineData {
    const start = dayjs('2026-06-01T00:00:00Z')
    const dates = Array.from({ length: 48 }, (_, i) => start.add(i, 'hour').toISOString())
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

export const WithActivity: Story = {
    render: () => <InvocationsSparkline data={exampleData()} loading={false} onDateRangeChange={() => {}} />,
}
