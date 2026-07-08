import type { Meta, StoryObj } from '@storybook/react'
import type { ChartAssemblyInput } from 'flint-chart/core'

import { FlintQuillChart } from './FlintQuillChart'

type Story = StoryObj<typeof FlintQuillChart>
const meta: Meta<typeof FlintQuillChart> = {
    title: 'Components/Flint quill chart',
    component: FlintQuillChart,
    tags: ['autodocs'],
    decorators: [
        (StoryComponent) => (
            <div style={{ width: 640, height: 360 }}>
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

const SIGNUPS_BY_PLAN: ChartAssemblyInput['data'] = {
    values: [
        { month: '2026-01-01', plan: 'Free', signups: 840 },
        { month: '2026-01-01', plan: 'Paid', signups: 120 },
        { month: '2026-02-01', plan: 'Free', signups: 910 },
        { month: '2026-02-01', plan: 'Paid', signups: 180 },
        { month: '2026-03-01', plan: 'Free', signups: 1050 },
        { month: '2026-03-01', plan: 'Paid', signups: 260 },
        { month: '2026-04-01', plan: 'Free', signups: 980 },
        { month: '2026-04-01', plan: 'Paid', signups: 340 },
    ],
}

const SEMANTIC_TYPES = { month: 'Date', plan: 'Category', signups: 'Quantity' }

export const GroupedBar: Story = {
    args: {
        input: {
            data: SIGNUPS_BY_PLAN,
            semantic_types: SEMANTIC_TYPES,
            chart_spec: {
                chartType: 'Grouped Bar Chart',
                encodings: { x: { field: 'plan' }, y: { field: 'signups', aggregate: 'sum' } },
            },
        },
    },
}

export const StackedBarOverTime: Story = {
    args: {
        input: {
            data: SIGNUPS_BY_PLAN,
            semantic_types: SEMANTIC_TYPES,
            chart_spec: {
                chartType: 'Stacked Bar Chart',
                encodings: { x: { field: 'month' }, y: { field: 'signups' }, color: { field: 'plan' } },
            },
        },
    },
}

export const MultiSeriesLine: Story = {
    args: {
        input: {
            data: SIGNUPS_BY_PLAN,
            semantic_types: SEMANTIC_TYPES,
            chart_spec: {
                chartType: 'Line Chart',
                encodings: { x: { field: 'month' }, y: { field: 'signups' }, color: { field: 'plan' } },
            },
        },
    },
}

export const StackedArea: Story = {
    args: {
        input: {
            data: SIGNUPS_BY_PLAN,
            semantic_types: SEMANTIC_TYPES,
            chart_spec: {
                chartType: 'Area Chart',
                encodings: { x: { field: 'month' }, y: { field: 'signups' }, color: { field: 'plan' } },
            },
        },
    },
}

export const Doughnut: Story = {
    args: {
        input: {
            data: SIGNUPS_BY_PLAN,
            semantic_types: SEMANTIC_TYPES,
            chart_spec: {
                chartType: 'Doughnut Chart',
                encodings: { color: { field: 'plan' }, size: { field: 'signups' } },
            },
        },
    },
}

export const UnsupportedChartType: Story = {
    args: {
        input: {
            data: SIGNUPS_BY_PLAN,
            semantic_types: SEMANTIC_TYPES,
            chart_spec: {
                chartType: 'Sankey Diagram',
                encodings: { x: { field: 'plan' }, y: { field: 'signups' } },
            },
        },
    },
}
