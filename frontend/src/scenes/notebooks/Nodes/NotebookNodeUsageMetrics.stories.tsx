import { Meta, StoryObj } from '@storybook/react'

import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

import { mswDecorator } from '~/mocks/browser'
import { UsageMetric } from '~/queries/schema/schema-general'

import { NotebookNodeType } from '../types'

const PERSON_ID = '01234567-89ab-cdef-0123-456789abcdef'
const CANVAS_SHORT_ID = `canvas-${PERSON_ID}`

const metrics: UsageMetric[] = [
    {
        id: 'metric-1',
        name: 'Events captured',
        value: 12400,
        previous: 9800,
        change_from_previous_pct: 26.5,
        format: 'numeric',
        display: 'number',
        interval: 7,
    },
    {
        id: 'metric-2',
        name: 'Dashboards viewed',
        value: 42,
        previous: 55,
        change_from_previous_pct: -23.6,
        format: 'numeric',
        display: 'number',
        interval: 7,
    },
]

// Person and group profiles mount their canvas read-only, so the node has to carry its own visible
// "Add metric" button — the notebook's settings panel is only reachable in editable notebooks.
function ReadOnlyProfileCanvas(): JSX.Element {
    return (
        <Notebook
            editable={false}
            shortId={CANVAS_SHORT_ID}
            mode="canvas"
            className="NotebookProfileCanvas"
            initialContent={{
                type: 'doc',
                content: [
                    {
                        type: NotebookNodeType.UsageMetrics,
                        attrs: {
                            personId: PERSON_ID,
                            nodeId: 'usage-metrics-node-1',
                            tabId: 'profile',
                            title: 'Usage metrics',
                        },
                    },
                ],
            }}
        />
    )
}

const meta: Meta = {
    component: ReadOnlyProfileCanvas,
    title: 'Scenes-App/Notebooks/Nodes/Usage Metrics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/UsageMetricsQuery/': () => [200, { results: metrics }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WithMetrics: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="usage-metrics-node-add-metric"]' } },
}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/UsageMetricsQuery/': () => [200, { results: [] }],
            },
        }),
    ],
    parameters: { testOptions: { waitForSelector: '[data-attr="product-introduction-usage metric"]' } },
}
