import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { BarChartWithLine, type DataPoint } from './DebugCHQueriesImpl'

// Values for the most recent hours, so the bars and line always sit against the right edge of the
// fixed 14-day hourly axis no matter when the snapshot runs — the shape stays deterministic.
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
}
export default meta

type Story = StoryObj<typeof BarChartWithLine>

export const QueryVolumeChart: Story = {
    args: {
        data: recentHours(96),
    },
}
