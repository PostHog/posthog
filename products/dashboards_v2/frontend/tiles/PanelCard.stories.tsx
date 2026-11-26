import type { Meta, StoryObj } from '@storybook/react'

import type { ContentPanel } from '../dashboard/dashboardTypes'
import { createChartPanel } from '../panels/chart/createChartPanel'
import { DEFAULT_PANELS } from '../panels/defaultPanels'
import { PanelCard } from './PanelCard'

const query = { language: 'hogql', query: 'select count() from events' } as const

const panel: ContentPanel = {
    type: 'chart',
    title: 'Signups',
    description: 'New accounts per day',
    refreshedAt: '2026-11-19T09:00:00Z',
    config: { query, viz: { type: 'line' } },
}

const meta: Meta<typeof PanelCard> = {
    title: 'Products/Dashboards v2/PanelCard',
    component: PanelCard,
    args: { panel, panels: DEFAULT_PANELS },
    parameters: { mockDate: '2026-11-20', testOptions: { snapshotBrowsers: [] } },
}
export default meta

/** A single panel on a page, with no dashboard around it. */
export const Standalone: StoryObj<typeof PanelCard> = {
    decorators: [
        (Story) => (
            <div className="h-64 w-96">
                <Story />
            </div>
        ),
    ],
}

const neverLoads = createChartPanel({ runQuery: () => new Promise(() => {}) })

/** Each built-in kind of chart while its query runs. */
export const Loading: StoryObj<typeof PanelCard> = {
    render: () => (
        <div className="grid grid-cols-3 gap-2">
            {(['line', 'bar', 'stat'] as const).map((type) => (
                <div key={type} className="h-64">
                    <PanelCard panel={{ ...panel, config: { query, viz: { type } } }} panels={[neverLoads]} />
                </div>
            ))}
        </div>
    ),
}
