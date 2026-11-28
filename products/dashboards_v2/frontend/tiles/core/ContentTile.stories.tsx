import type { Meta, StoryObj } from '@storybook/react'

import { createChartPanel } from '../../panels/chart/createChartPanel'
import type { SavedPanel } from '../../panels/core/panelSchema'
import { markdownPanel } from '../../panels/markdown/markdownSpec'
import { ContentTile } from './ContentTile'

const PANELS = [createChartPanel({ sampleData: true }), markdownPanel]

const signups: SavedPanel = {
    type: 'chart',
    title: 'Signups',
    description: 'People who signed up each day',
    config: { query: { language: 'hogql', query: 'select count() from events' }, viz: { type: 'line' } },
}

const note: SavedPanel = { type: 'markdown', config: { text: '**Signups** dipped after the pricing change.' } }

const meta: Meta<typeof ContentTile> = {
    title: 'Products/Dashboards v2/ContentTile',
    component: ContentTile,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

/** Panels rendered as tiles on a page of their own, with no dashboard, grid or controller. */
export const OnItsOwn: StoryObj<typeof ContentTile> = {
    render: () => (
        <div className="flex gap-4">
            <div className="flex h-72 w-[28rem] flex-col">
                <ContentTile panel={signups} panels={PANELS} />
            </div>
            <div className="flex h-72 w-72 flex-col">
                <ContentTile panel={note} panels={PANELS} />
            </div>
        </div>
    ),
}
