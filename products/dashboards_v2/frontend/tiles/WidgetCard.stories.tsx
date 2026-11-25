import type { Meta, StoryObj } from '@storybook/react'

import type { ContentWidget } from '../dashboard/dashboardTypes'
import { createChartWidget } from '../widgets/chart/createChartWidget'
import { DEFAULT_WIDGETS } from '../widgets/defaultWidgets'
import { WidgetCard } from './WidgetCard'

const query = { language: 'hogql', query: 'select count() from events' } as const

const widget: ContentWidget = {
    type: 'chart',
    title: 'Signups',
    description: 'New accounts per day',
    refreshedAt: '2026-11-19T09:00:00Z',
    config: { query, viz: { type: 'line' } },
}

const meta: Meta<typeof WidgetCard> = {
    title: 'Products/Dashboards v2/WidgetCard',
    component: WidgetCard,
    args: { widget, widgets: DEFAULT_WIDGETS },
    parameters: { mockDate: '2026-11-20', testOptions: { snapshotBrowsers: [] } },
}
export default meta

/** A single widget on a page, with no dashboard around it. */
export const Standalone: StoryObj<typeof WidgetCard> = {
    decorators: [
        (Story) => (
            <div className="h-64 w-96">
                <Story />
            </div>
        ),
    ],
}

const neverLoads = createChartWidget({ runQuery: () => new Promise(() => {}) })

/** Each built-in kind of chart while its query runs. */
export const Loading: StoryObj<typeof WidgetCard> = {
    render: () => (
        <div className="grid grid-cols-3 gap-2">
            {(['line', 'bar', 'stat'] as const).map((type) => (
                <div key={type} className="h-64">
                    <WidgetCard widget={{ ...widget, config: { query, viz: { type } } }} widgets={[neverLoads]} />
                </div>
            ))}
        </div>
    ),
}
