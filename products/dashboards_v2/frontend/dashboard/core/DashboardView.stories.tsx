import type { Meta, StoryObj } from '@storybook/react'

import { createChartPanel } from '../../panels/chart/createChartPanel'
import { markdownPanel } from '../../panels/markdown/markdownSpec'
import { dashboardFromJson } from '../document/dashboardFromJson'
import { DashboardView } from './DashboardView'

const PANELS = [createChartPanel({ sampleData: true }), markdownPanel]

const chart = (type: string): unknown => ({
    type: 'chart',
    title: `Events as a ${type} chart`,
    config: { query: { language: 'hogql', query: 'select count() from events' }, viz: { type } },
})

// A document as a product would write it in code. Nothing loads it from a board, and nothing saves it.
const { dashboard } = dashboardFromJson(
    {
        version: 2,
        title: 'Written in code',
        tabs: [
            {
                id: 'overview',
                title: 'Overview',
                tiles: [
                    { id: 'line', place: { x: 0, y: 0, w: 16, h: 14 }, panel: chart('line') },
                    { id: 'metric', place: { x: 16, y: 0, w: 8, h: 14 }, panel: chart('metric') },
                    {
                        id: 'note',
                        place: { x: 0, y: 14, w: 24, h: 6 },
                        panel: { type: 'markdown', config: { text: 'This dashboard is read-only.' } },
                    },
                ],
            },
            {
                id: 'details',
                title: 'Details',
                tiles: [{ id: 'bar', place: { x: 0, y: 0, w: 24, h: 14 }, panel: chart('bar') }],
            },
        ],
    },
    PANELS
)

const meta: Meta<typeof DashboardView> = {
    title: 'Products/Dashboards v2/DashboardView',
    component: DashboardView,
    parameters: { layout: 'fullscreen', testOptions: { snapshotBrowsers: [] } },
}
export default meta

/** A read-only dashboard rendered from JSON. It passes only the document and its panel types. */
export const ReadOnlyFromJson: StoryObj<typeof DashboardView> = {
    render: () => <DashboardView dashboard={dashboard!} panels={PANELS} surface="storybook" />,
}
