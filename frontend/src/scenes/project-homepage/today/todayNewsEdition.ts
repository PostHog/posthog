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
        title: 'Checkout conversion fell 12% after the address form change',
        summary:
            'Mobile visitors leave at the new address step, and desktop is flat. The drop started in the same hour as the change.',
        change: -12,
        tone: 'risk',
        divePrompt: 'Why did checkout conversion fall after the address form change, and what should we fix first?',
        metricLabel: 'Checkout conversion, last 14 days',
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
            title: 'Three alerts are firing',
            summary: 'Event volume drop, client API failures, and checkout errors.',
            change: null,
            tone: 'risk',
            divePrompt: 'Three alerts are firing. Which one should we look at first, and what is the likely cause?',
        },
        {
            id: 'pricing-experiment',
            product: 'experiments',
            productLabel: 'Experiments',
            title: 'Pricing page layout ended, and variant B won',
            summary: 'More plan clicks, with a 96% chance to be better.',
            change: 8,
            tone: 'good',
            divePrompt: 'Variant B of the pricing page layout won. What should we do to roll it out safely?',
        },
        {
            id: 'checkout-error',
            product: 'error_tracking',
            productLabel: 'Error tracking',
            title: 'A new checkout error reached 214 users',
            summary: '‘Cannot read properties of null’ on the checkout page, since Tuesday.',
            change: null,
            tone: 'risk',
            divePrompt: 'A new checkout error reached 214 users. What causes it, and how do we fix it?',
        },
    ],
    briefs: [
        'Two experiments started: the onboarding checklist and search ranking',
        '12 new feature flags and 3 new dashboards',
        '41 deploys to production',
    ],
}
