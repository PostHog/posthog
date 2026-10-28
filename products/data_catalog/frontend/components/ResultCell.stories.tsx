import type { Meta, StoryObj } from '@storybook/react'

import type { DataCatalogMetricApi } from '../generated/api.schemas'
import { MetricDefinition } from './MetricDefinition'

interface StoryProps {
    narrow?: boolean
}

const days = Array.from({ length: 31 }, (_, index) => `2026-09-${String(index + 1).padStart(2, '0')}`)
const row = {
    data: days.map((_, index) => 100 + ((index * 37) % 300)),
    days,
    count: 8247,
    label: 'example event',
    description: 'Counts every example event that a person sends from the web app, excluding internal test accounts',
    filter: { insight: 'TRENDS', interval: 'day', date_from: '2026-09-01', display: 'ActionsLineGraph' },
}

const metric = {
    id: 'metric-1',
    name: 'example_events',
    definition_kind: 'TrendsQuery',
    definition: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: 'example event' }] },
    status: 'approved',
} as unknown as DataCatalogMetricApi

const meta: Meta<StoryProps> = {
    title: 'Data catalog/Metric run result cell',
    parameters: { viewMode: 'story', testOptions: { waitForSelector: '.react-json-view' } },
    render: ({ narrow }) => (
        <div className={narrow ? 'w-130' : undefined}>
            <MetricDefinition
                metric={metric}
                editingDefinition={false}
                draftMarkdown=""
                saving={false}
                runResult={{ results: [row, { ...row, label: 'second event', count: 12 }] }}
                runResultLoading={false}
                onDraftMarkdown={() => {}}
                onEdit={() => {}}
                onStartEditingMarkdown={() => {}}
                onSaveMarkdown={() => {}}
                onRun={() => {}}
                onRunWithAI={() => {}}
            />
        </div>
    ),
}

export default meta

type Story = StoryObj<StoryProps>

export const LongValuesCollapse: Story = {}

export const LongValuesCollapseNarrow: Story = { args: { narrow: true } }
