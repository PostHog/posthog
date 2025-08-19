import { GraphDataPoint, GraphResponse, OverviewResponse, TableResponse } from '../types/schemas'

export const generateExampleGraphDatePoints = (days: number, baseValue: number, variance: number): GraphDataPoint[] => {
    const points = []
    const today = new Date()

    for (let i = days - 1; i >= 0; i--) {
        const date = new Date(today.getTime())
        date.setDate(date.getDate() - i)

        const randomFactor = 0.8 + Math.random() * 0.4 // 0.8 to 1.2
        const value = Math.round(baseValue * randomFactor + (Math.random() - 0.5) * variance)
        const previousValue = Math.round(value * (0.75 + Math.random() * 0.5)) // Previous period variation

        points.push({
            date: date.toISOString().split('T')[0],
            value: Math.max(0, value),
            previousValue: Math.max(0, previousValue),
        })
    }

    return points
}

export const exampleGraphVisitorsResponse: GraphResponse = {
    title: 'Daily Visitors',
    metric: 'visitors',
    unit: 'visitors',
    points: generateExampleGraphDatePoints(14, 1500, 300),
}

export const exampleGraphPageviewsResponse: GraphResponse = {
    title: 'Page Views Over Time',
    metric: 'pageviews',
    unit: 'views',
    points: generateExampleGraphDatePoints(30, 5000, 1000),
}

export const exampleGraphRevenueResponse: GraphResponse = {
    title: 'Daily Revenue',
    metric: 'revenue',
    unit: '$',
    points: generateExampleGraphDatePoints(7, 2500, 500),
}

export const exampleOverviewResponse: OverviewResponse = {
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

export const exampleTableResponse: TableResponse = {
    columns: [
        {
            key: 'breakdown_value',
            label: 'Page',
            type: 'string' as const,
            sortable: true,
        },
        {
            key: 'visitors',
            label: 'Visitors',
            type: 'number' as const,
            sortable: true,
        },
        {
            key: 'pageviews',
            label: 'Page Views',
            type: 'number' as const,
            sortable: true,
        },
        {
            key: 'bounce_rate',
            label: 'Bounce Rate',
            type: 'percentage' as const,
            sortable: true,
        },
    ],
    rows: [
        {
            breakdown_value: '/home',
            visitors: 5420,
            pageviews: 8230,
            bounce_rate: 23.4,
            fillRatio: 1.0,
        },
        {
            breakdown_value: '/about',
            visitors: 3210,
            pageviews: 4560,
            bounce_rate: 31.2,
            fillRatio: 0.59,
        },
        {
            breakdown_value: '/products',
            visitors: 2840,
            pageviews: 5120,
            bounce_rate: 28.7,
            fillRatio: 0.52,
        },
        {
            breakdown_value: '/contact',
            visitors: 1680,
            pageviews: 2340,
            bounce_rate: 45.1,
            fillRatio: 0.31,
        },
    ],
    count: 50,
    next: 'next-page-token',
    previous: undefined,
}
