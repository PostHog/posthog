import type { Meta, StoryObj } from '@storybook/react'

import { Graph } from '../components'
import {
    exampleGraphPageviewsResponse,
    exampleGraphRevenueResponse,
    exampleGraphVisitorsResponse,
    generateExampleGraphDatePoints,
} from './exampleData'

const meta: Meta<typeof Graph> = {
    title: 'Analytics/Graph',
    component: Graph,
    parameters: {
        layout: 'padded',
        docs: {
            description: {
                component: 'Display linear area charts with current and previous period data.',
            },
        },
    },
    argTypes: {
        height: {
            control: { type: 'range', min: 200, max: 600, step: 50 },
        },
    },
}

export default meta
type Story = StoryObj<typeof Graph>

export const Default: Story = {
    args: {
        response: exampleGraphVisitorsResponse,
        loading: false,
        height: 300,
    },
}

export const Loading: Story = {
    args: {
        loading: true,
        height: 300,
    },
}

export const WithError: Story = {
    args: {
        error: {
            error: 'Failed to load chart data',
            details: 'Unable to connect to analytics service. Please try again later.',
        },
        height: 300,
    },
}

export const WithoutPreviousData: Story = {
    args: {
        response: {
            ...exampleGraphVisitorsResponse,
            points: exampleGraphVisitorsResponse.points.map((point) => ({
                date: point.date,
                value: point.value,
            })),
        },
        loading: false,
        height: 300,
    },
}

export const LongTimePeriod: Story = {
    args: {
        response: exampleGraphPageviewsResponse,
        loading: false,
        height: 400,
    },
}

export const ShortTimePeriod: Story = {
    args: {
        response: exampleGraphRevenueResponse,
        loading: false,
        height: 300,
    },
}

export const TallChart: Story = {
    args: {
        response: exampleGraphVisitorsResponse,
        loading: false,
        height: 500,
    },
}

export const CompactChart: Story = {
    args: {
        response: exampleGraphVisitorsResponse,
        loading: false,
        height: 200,
    },
}

export const WithHighValues: Story = {
    args: {
        response: {
            title: 'High Volume Metrics',
            metric: 'impressions',
            unit: 'impressions',
            points: generateExampleGraphDatePoints(14, 50000, 15000),
        },
        loading: false,
        height: 350,
    },
}

export const WithLowValues: Story = {
    args: {
        response: {
            title: 'Low Volume Metrics',
            metric: 'conversions',
            unit: 'conversions',
            points: generateExampleGraphDatePoints(14, 25, 10),
        },
        loading: false,
        height: 300,
    },
}

export const NoTitle: Story = {
    args: {
        response: {
            metric: 'visitors',
            unit: 'visitors',
            points: exampleGraphVisitorsResponse.points,
        },
        loading: false,
        height: 300,
    },
}

export const ZeroValues: Story = {
    args: {
        response: {
            title: 'Sparse Data',
            metric: 'events',
            unit: 'events',
            points: [
                { date: '2024-01-01', value: 0, previousValue: 0 },
                { date: '2024-01-02', value: 5, previousValue: 2 },
                { date: '2024-01-03', value: 0, previousValue: 0 },
                { date: '2024-01-04', value: 12, previousValue: 8 },
                { date: '2024-01-05', value: 3, previousValue: 1 },
                { date: '2024-01-06', value: 0, previousValue: 0 },
                { date: '2024-01-07', value: 15, previousValue: 10 },
            ],
        },
        loading: false,
        height: 300,
    },
}
