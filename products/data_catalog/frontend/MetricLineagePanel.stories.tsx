import type { Meta, StoryObj } from '@storybook/react'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { DataCatalogMetricApi } from './generated/api.schemas'
import { MetricLineagePanel, MetricLineagePanelProps } from './MetricLineagePanel'

function metric(overrides: Partial<DataCatalogMetricApi> = {}): DataCatalogMetricApi {
    return {
        id: 'metric-1',
        name: 'weekly_active_accounts',
        display_name: 'Weekly active accounts',
        description: 'Accounts with at least one event in the last 7 days',
        definition: { kind: 'HogQLQuery', query: 'select count() from events' },
        definition_kind: 'HogQLQuery',
        referenced_table_names: ['events'],
        status: 'approved',
        is_drifted: false,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        ...overrides,
    } as DataCatalogMetricApi
}

const METRIC = metric()
const MARKDOWN_METRIC = metric({ definition_kind: 'MarkdownDefinition' })

function node(partial: Pick<DataModelingNode, 'id' | 'name' | 'type'> & Partial<DataModelingNode>): DataModelingNode {
    return {
        dag: 'dag-1',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        upstream_count: 0,
        downstream_count: 0,
        ...partial,
    }
}

const NODES: DataModelingNode[] = [
    node({ id: '1', name: 'events', type: 'table' }),
    node({ id: '2', name: 'accounts_view', type: 'view' }),
    node({ id: '3', name: 'weekly_active_accounts', type: 'metric', metric_id: 'metric-1' }),
]
const EDGES: DataModelingEdge[] = [
    { id: 'e1', source_id: '1', target_id: '2', dag: 'dag-1', properties: {}, created_at: '', updated_at: '' },
    { id: 'e2', source_id: '2', target_id: '3', dag: 'dag-1', properties: {}, created_at: '', updated_at: '' },
]

const BASE: MetricLineagePanelProps = {
    metric: METRIC,
    lineage: { nodes: NODES, edges: EDGES },
    lineageLoading: false,
    lineageProblem: null,
    onRetry: () => {},
    onEditDefinition: () => {},
}

function atWidths(props: MetricLineagePanelProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="w-[960px]">
                <MetricLineagePanel {...props} />
            </div>
            <div className="w-[480px]">
                <MetricLineagePanel {...props} />
            </div>
        </div>
    )
}

type Story = StoryObj<typeof MetricLineagePanel>
const meta: Meta<typeof MetricLineagePanel> = {
    title: 'Products/Data catalog/Metric lineage',
    component: MetricLineagePanel,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}

export default meta

export const Graph: Story = { render: () => atWidths(BASE) }

export const Loading: Story = {
    render: () => atWidths({ ...BASE, lineage: null, lineageLoading: true }),
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const NoDefinition: Story = {
    render: () => atWidths({ ...BASE, metric: MARKDOWN_METRIC, lineage: null }),
}

export const BeingPrepared: Story = {
    render: () => atWidths({ ...BASE, lineage: null, lineageProblem: 'not_ready' }),
}

export const NoWarehouseAccess: Story = {
    render: () => atWidths({ ...BASE, lineage: null, lineageProblem: 'no_warehouse_access' }),
}

export const LoadFailed: Story = {
    render: () => atWidths({ ...BASE, lineage: null, lineageProblem: 'failed' }),
}

const ISOLATED_METRIC_NODE = node({
    id: '3',
    name: 'weekly_active_accounts',
    type: 'metric',
    metric_id: 'metric-1',
    lineage_issue: { kind: 'unresolved', detail: 'accounts_view', at: '2024-01-01T00:00:00Z' },
})

export const LineageIssue: Story = {
    render: () => atWidths({ ...BASE, lineage: { nodes: [ISOLATED_METRIC_NODE], edges: [] } }),
}
