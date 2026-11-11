import { ProductKey } from '~/queries/schema/schema-general'

export interface ProductPushPrompt {
    title: string
    facts: string[]
}

/**
 * A pushed product without a prompt gets no row in Today, because the sidebar's promo copy reads as an ad
 * next to the facts in that list. "Isn't set up" is what the campaign's usage check measures: the project
 * has no intent for the product.
 */
export const PRODUCT_PUSH_PROMPTS: Partial<Record<string, ProductPushPrompt>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        title: 'Product analytics isn’t set up in this project yet',
        facts: ['Insights chart trends, funnels and retention from your events', 'Create an insight'],
    },
    [ProductKey.WEB_ANALYTICS]: {
        title: 'No one has opened web analytics in this project yet',
        facts: ['It shows traffic, sources and top pages from the pageviews you send', 'Open web analytics'],
    },
    [ProductKey.SESSION_REPLAY]: {
        title: 'Session replay isn’t set up in this project yet',
        facts: ['Recordings show where people get stuck', 'Turn on recordings'],
    },
    [ProductKey.ERROR_TRACKING]: {
        title: 'Error tracking isn’t set up in this project yet',
        facts: ['It groups exceptions and shows who they affect', 'Set up error tracking'],
    },
    [ProductKey.FEATURE_FLAGS]: {
        title: 'Feature flags aren’t set up in this project yet',
        facts: ['Flags release a change to some users before everyone', 'Create a flag'],
    },
    [ProductKey.EXPERIMENTS]: {
        title: 'This project hasn’t run an experiment yet',
        facts: ['Experiments measure whether a change moved a metric', 'Start an experiment'],
    },
    [ProductKey.SURVEYS]: {
        title: 'Surveys aren’t set up in this project yet',
        facts: ['Surveys ask people questions inside your product', 'Create a survey'],
    },
    [ProductKey.LOGS]: {
        title: 'Logs aren’t set up in this project yet',
        facts: ['Logs show what your app did, next to your events', 'Set up logs'],
    },
    [ProductKey.DATA_WAREHOUSE]: {
        title: 'No one has used the SQL editor in this project yet',
        facts: ['It queries your events and connected sources', 'Open the SQL editor'],
    },
    [ProductKey.AI_OBSERVABILITY]: {
        title: 'AI observability isn’t set up in this project yet',
        facts: ['It shows the cost, latency and trace of each LLM call', 'Set up AI observability'],
    },
    [ProductKey.WORKFLOWS]: {
        title: 'Workflows aren’t set up in this project yet',
        facts: ['Workflows send messages and run actions when events happen', 'Create a workflow'],
    },
}
