import type { Meta, StoryObj } from '@storybook/react'

import type { ContentWidget } from '../dashboard/dashboardTypes'
import { DEFAULT_WIDGETS } from '../widgets/defaultWidgets'
import { WidgetCard } from './WidgetCard'

const widget: ContentWidget = {
    type: 'chart',
    title: 'Signups',
    description: 'New accounts per day',
    refreshedAt: '2026-11-19T09:00:00Z',
    config: { query: { language: 'hogql', query: 'select count() from events' }, viz: { type: 'line' } },
}

const meta: Meta<typeof WidgetCard> = {
    title: 'Products/Dashboards v2/WidgetCard',
    component: WidgetCard,
    args: { widget, widgets: DEFAULT_WIDGETS },
    decorators: [
        (Story) => (
            <div className="h-64 w-96">
                <Story />
            </div>
        ),
    ],
    parameters: { mockDate: '2026-11-20', testOptions: { snapshotBrowsers: [] } },
}
export default meta

/** A single widget on a page, with no dashboard around it. */
export const Standalone: StoryObj<typeof WidgetCard> = {}
