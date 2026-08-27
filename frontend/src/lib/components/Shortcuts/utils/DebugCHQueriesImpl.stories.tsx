import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { BarChartWithLine, type DataPoint } from './DebugCHQueriesImpl'

// Recent hours so the bars and line sit against the right edge of the fixed 14-day hourly axis.
// Built in render so it shares the mocked clock with the component's own label generation, which
// keeps the data aligned to the axis and the snapshot deterministic.
function recentHours(count: number): DataPoint[] {
    const now = dayjs().startOf('hour')
    return Array.from({ length: count }, (_, i) => ({
        hour: now.subtract(count - 1 - i, 'hour').format('YYYY-MM-DDTHH:00:00'),
        successful_queries: 40 + ((i * 7) % 60),
        exceptions: (i * 3) % 11,
        avg_response_time_ms: 120 + ((i * 13) % 240),
    }))
}

const meta: Meta<typeof BarChartWithLine> = {
    title: 'Components/DebugCHQueries',
    component: BarChartWithLine,
    parameters: {
        layout: 'centered',
        mockDate: '2023-01-15 12:00:00',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof BarChartWithLine>

// BarChartWithLine fills its flex parent, so give it a column container with a definite size —
// otherwise the chart resolves to size 0 and quill paints a 0-size canvas.
export const QueryVolumeChart: Story = {
    render: () => (
        <div className="h-[340px] w-[760px] flex flex-col">
            <BarChartWithLine data={recentHours(96)} />
        </div>
    ),
}
