import type { TodayTone } from './todayTone'

export interface TodayNewsStory {
    id: string
    product: string
    productLabel: string
    title: string
    summary: string
    change: number | null
    tone: TodayTone
    divePrompt: string
}

export interface TodayNewsLeadStory extends TodayNewsStory {
    metricLabel: string
    metricValue: string
    series: number[]
    seriesLabels: string[]
}

export interface TodayNewsEdition {
    id: string
    isSample: boolean
    lead: TodayNewsLeadStory
    stories: TodayNewsStory[]
    briefs: string[]
}

const SAMPLE_SERIES = [41, 40.4, 41.8, 41.2, 40.6, 41.1, 41.6, 40.8, 41.3, 36.2, 33.4, 32.1, 31.6, 31.4]

export const SAMPLE_NEWS_EDITION: TodayNewsEdition = {
    id: 'sample-1',
    isSample: true,
    lead: {
        id: 'checkout-conversion',
        product: 'product_analytics',
        productLabel: 'Product analytics',
        title: 'Checkout conversion dropped 12% when the new address form shipped',
        summary: 'Mobile visitors now stop at the address step. Desktop is flat, so the form is the likely cause.',
        change: -12,
        tone: 'risk',
        divePrompt: 'Why did checkout conversion fall after the address form change, and what should we fix first?',
        metricLabel: 'Last 14 days',
        metricValue: '31.4%',
        series: SAMPLE_SERIES,
        seriesLabels: SAMPLE_SERIES.map((_, index) =>
            index === SAMPLE_SERIES.length - 1 ? 'Today' : `${SAMPLE_SERIES.length - 1 - index} days ago`
        ),
    },
    stories: [
        {
            id: 'firing-alerts',
            product: 'alerts',
            productLabel: 'Alerts',
            title: '3 alerts are firing, and 2 of them point at checkout',
            summary: 'Checkout errors affect the most users, so start there.',
            change: null,
            tone: 'risk',
            divePrompt: 'Three alerts are firing. Which one should we look at first, and what is the likely cause?',
        },
        {
            id: 'pricing-experiment',
            product: 'experiments',
            productLabel: 'Experiments',
            title: 'Variant B of the pricing page won',
            summary: 'More plan clicks, with a 96% chance that B is really better. It is ready to roll out.',
            change: 8,
            tone: 'good',
            divePrompt: 'Variant B of the pricing page layout won. What should we do to roll it out safely?',
        },
        {
            id: 'checkout-error',
            product: 'error_tracking',
            productLabel: 'Error tracking',
            title: 'A new checkout error reached 214 users',
            summary: 'A null error on checkout since Tuesday. Nobody owns it yet.',
            change: null,
            tone: 'risk',
            divePrompt: 'A new checkout error reached 214 users. What causes it, and how do we fix it?',
        },
    ],
    briefs: ['2 experiments started', '12 new feature flags', '41 deploys to production'],
}
