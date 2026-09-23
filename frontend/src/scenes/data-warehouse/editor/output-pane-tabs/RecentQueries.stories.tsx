import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { outputPaneLogic } from '../outputPaneLogic'
import { sqlEditorLogic } from '../sqlEditorLogic'
import { RecentQueries } from './RecentQueries'

const STORY_TAB_ID = 'story-recent-queries'

const COLUMNS = ['query', 'last_run_at', 'last_exception_code']

const RESULTS = [
    ["SELECT count() FROM events WHERE event = '$pageview'", '2024-01-14T21:58:00Z', 0],
    [
        'SELECT\n    toStartOfDay(timestamp) AS day,\n    count() AS pageviews\nFROM events\nGROUP BY day\nORDER BY day DESC',
        '2024-01-14T21:31:00Z',
        0,
    ],
    ["SELECT * FROM orders WHERE stat = 'paid'", '2024-01-13T17:02:00Z', 47],
]

function BoundRecentQueries(): JSX.Element {
    return (
        <BindLogic logic={outputPaneLogic} props={{ tabId: STORY_TAB_ID }}>
            <BindLogic logic={sqlEditorLogic} props={{ tabId: STORY_TAB_ID }}>
                <RecentQueries />
            </BindLogic>
        </BindLogic>
    )
}

type Story = StoryObj<typeof RecentQueries>
const meta: Meta<typeof RecentQueries> = {
    title: 'Data Warehouse/Recent queries',
    component: RecentQueries,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        testOptions: { viewport: { width: 560, height: 600 } },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [200, { results: RESULTS, columns: COLUMNS }],
            },
        }),
    ],
    render: () => <BoundRecentQueries />,
}

export default meta

export const WithQueries: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [200, { results: [], columns: COLUMNS }],
            },
        }),
    ],
}
