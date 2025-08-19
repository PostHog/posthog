import type { Meta, StoryObj } from '@storybook/react'
import { Overview } from '../components'
import { OverviewResponse } from '../types/schemas'

const meta: Meta<typeof Overview> = {
    title: 'Analytics/Overview',
    component: Overview,
    parameters: {
        layout: 'padded',
        docs: {
            description: {
                component: 'Display key metrics with change indicators and tooltips.',
            },
        },
    },
    argTypes: {
        onClick: { action: 'number clicked' },
    },
}

export default meta
type Story = StoryObj<typeof Overview>

// Sample data for stories
const exampleOverviewResponse: OverviewResponse = {
    visitors: {
        key: 'visitors',
        label: 'Unique Visitors',
        value: 12453,
        previousValue: 10234,
        changePercentage: 21.7,
        isIncreaseGood: true,
        format: 'number',
    },
    bounce_rate: {
        key: 'bounce_rate',
        label: 'Bounce Rate',
        value: 34.2,
        previousValue: 41.1,
        changePercentage: -16.8,
        isIncreaseGood: false,
        format: 'percentage',
    },
    session_duration: {
        key: 'session_duration',
        label: 'Session Duration',
        value: 142,
        previousValue: 138,
        changePercentage: 2.9,
        isIncreaseGood: true,
        format: 'duration_seconds',
    },
    conversion_rate: {
        key: 'conversion_rate',
        label: 'Conversion Rate',
        value: 3.12,
        previousValue: 3.45,
        changePercentage: -10.6,
        isIncreaseGood: true,
        format: 'percentage' as const,
    },
    revenue: {
        key: 'revenue',
        label: 'Revenue',
        value: 15234.5,
        previousValue: 12987.25,
        changePercentage: 17.3,
        isIncreaseGood: true,
        format: 'currency' as const,
    },
}

export const Default: Story = {
    args: {
        response: exampleOverviewResponse,
        loading: false,
    },
}

export const Loading: Story = {
    args: {
        loading: true,
    },
}

export const WithError: Story = {
    args: {
        error: {
            error: 'Failed to load metrics',
            details: 'Network connection error. Please try again.',
        },
    },
}

export const WithoutPreviousData: Story = {
    args: {
        response: Object.fromEntries(
            Object.entries(exampleOverviewResponse).map(([key, item]) => [
                key,
                {
                    ...item,
                    previousValue: undefined,
                    changePercentage: undefined,
                },
            ])
        ),
        loading: false,
    },
}

export const SingleMetric: Story = {
    args: {
        response: {
            visitors: exampleOverviewResponse.visitors,
        },
        loading: false,
    },
}

export const LargeNumbers: Story = {
    args: {
        response: {
            visitors: {
                key: 'visitors',
                label: 'Very Large Number',
                value: 2847593821,
                previousValue: 2234567123,
                changePercentage: 27.4,
                isIncreaseGood: true,
                format: 'number' as const,
            },
            views: {
                key: 'views',
                label: 'Small Number',
                value: 23,
                previousValue: 18,
                changePercentage: 27.8,
                isIncreaseGood: true,
                format: 'number' as const,
            },
        },
        loading: false,
    },
}

export const WithClickHandlers: Story = {
    args: {
        response: exampleOverviewResponse,
        loading: false,
        onClick: (key: string) => {
            alert(`Clicked on ${key}`)
        },
    },
    parameters: {
        docs: {
            description: {
                story: 'Click on any metric card to see the click handler in action.',
            },
        },
    },
}
