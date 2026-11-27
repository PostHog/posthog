import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { EntityDetailChart } from './EntityDetailChart'

const DAYS = Array.from({ length: 7 }, (_, day) => `2026-11-${String(18 + day).padStart(2, '0')}T00:00:00Z`)

const meta: Meta<typeof EntityDetailChart> = {
    title: 'Scenes-App/AI observability/Diagnostics/Entity detail chart',
    component: EntityDetailChart,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        detail: {
            status: 'ready',
            value: {
                item: { series: [12, 15, 9, 20, 22, 25, 31] },
                previousSeries: [8, 10, 7, 9, 12, 11, 14],
                bucketStarts: DAYS,
            },
        },
        timezone: 'UTC',
        notFound: { title: 'No calls in this date range', description: 'Pick a wider date range to see it.' },
        failedTitle: 'Could not load this tool',
        onRetry: () => {},
        'data-attr': 'tool-drawer',
    },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof EntityDetailChart>

export const Ready: Story = {}

export const NotFound: Story = { args: { detail: { status: 'not_found' } } }

export const Failed: Story = { args: { detail: { status: 'error' } } }
