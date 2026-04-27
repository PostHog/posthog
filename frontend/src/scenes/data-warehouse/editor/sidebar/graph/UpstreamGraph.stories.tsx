import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { LineageGraph } from '~/types'

import { sqlEditorLogic } from '../../sqlEditorLogic'
import { UpstreamGraph } from './UpstreamGraph'

const MOCK_LINEAGE_WITH_GRAPH: LineageGraph = {
    nodes: [
        { id: '1', name: 'orders', type: 'table' },
        { id: '2', name: 'customers', type: 'table' },
        {
            id: '3',
            name: 'revenue_summary',
            type: 'view',
            last_run_at: '2024-01-15T10:30:00Z',
            status: 'Completed',
        },
        { id: '4', name: 'monthly_report', type: 'view' },
    ],
    edges: [
        { source: '1', target: '3' },
        { source: '2', target: '3' },
        { source: '3', target: '4' },
    ],
}

const MOCK_LINEAGE_SINGLE_NODE: LineageGraph = {
    nodes: [{ id: '1', name: 'raw_events', type: 'table' }],
    edges: [],
}

const TAB_ID = 'story-tab'

function GraphLoader({ lineage }: { lineage: LineageGraph }): JSX.Element {
    const { loadUpstreamSuccess } = useActions(sqlEditorLogic({ tabId: TAB_ID }))
    useDelayedOnMountEffect(() => loadUpstreamSuccess(lineage))
    return <UpstreamGraph tabId={TAB_ID} />
}

type Story = StoryObj<typeof UpstreamGraph>
const meta: Meta<typeof UpstreamGraph> = {
    title: 'Scenes-App/Data Warehouse/Editor/Upstream graph',
    component: UpstreamGraph,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
}

export default meta

export const WithGraph: Story = {
    render: () => <GraphLoader lineage={MOCK_LINEAGE_WITH_GRAPH} />,
}

export const SingleNode: Story = {
    render: () => <GraphLoader lineage={MOCK_LINEAGE_SINGLE_NODE} />,
}

export const EmptyState: Story = {
    render: () => <UpstreamGraph tabId={TAB_ID} />,
}
