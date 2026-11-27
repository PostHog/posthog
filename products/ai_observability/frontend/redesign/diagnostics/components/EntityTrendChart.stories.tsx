import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { EntityTrendChart } from './EntityTrendChart'

const DAYS = Array.from({ length: 7 }, (_, day) => `2026-11-${String(18 + day).padStart(2, '0')}T00:00:00Z`)

const meta: Meta<typeof EntityTrendChart> = {
    title: 'Scenes-App/AI observability/Diagnostics/Entity trend chart',
    component: EntityTrendChart,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        series: [12, 15, 9, 20, 22, 25, 31],
        previousSeries: [8, 10, 7, 9, 12, 11, 14],
        bucketStarts: DAYS,
        timezone: 'UTC',
    },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof EntityTrendChart>

export const AgainstPreviousPeriod: Story = {}

export const NoPreviousPeriod: Story = { args: { previousSeries: [] } }
