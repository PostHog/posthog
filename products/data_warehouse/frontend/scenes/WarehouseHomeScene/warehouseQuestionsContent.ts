// The example questions on the warehouse home page. Each one pairs PostHog data with a
// category of external tool and links to its pocket guide on posthog.com, which holds the full skill.
// Edit the copy here; the page renders whatever this list holds.

// The getting started card scrolls to the questions section by this id.
export const WAREHOUSE_QUESTIONS_SECTION_ID = 'warehouse-questions'

export type WarehouseToolCategory = 'revenue' | 'support' | 'crm' | 'ads'

// Each tool listed here must be a source people can connect from the new source page.
export const WAREHOUSE_TOOL_CATEGORIES: Record<
    WarehouseToolCategory,
    { label: string; pluralLabel: string; tools: string[] }
> = {
    revenue: {
        label: 'Revenue tool',
        pluralLabel: 'Revenue tools',
        tools: ['Stripe', 'Chargebee', 'Paddle', 'Recurly'],
    },
    support: {
        label: 'Support tool',
        pluralLabel: 'Support tools',
        tools: ['Zendesk', 'Intercom', 'Freshdesk', 'Help Scout'],
    },
    crm: { label: 'CRM', pluralLabel: 'CRMs', tools: ['Salesforce', 'HubSpot', 'Pipedrive', 'Attio'] },
    ads: {
        label: 'Ad platform',
        pluralLabel: 'Ad platforms',
        tools: ['Google Ads', 'Meta Ads', 'LinkedIn Ads', 'TikTok Ads'],
    },
}

export interface WarehouseQuestion {
    // pinned: sent as the `question` property of 'warehouse question clicked' and used in data-attr values
    id: string
    question: string
    description: string
    posthogData: string
    toolCategories: WarehouseToolCategory[]
    guideUrl: string
}

const GUIDES = 'https://posthog.com/pocket-guides/data-stack'

export const WAREHOUSE_QUESTIONS: WarehouseQuestion[] = [
    {
        id: 'features-drive-revenue',
        question: 'Which features drive revenue?',
        description:
            'Join product usage to your revenue data to find the features that bring in the most revenue per user.',
        posthogData: 'Events',
        toolCategories: ['revenue'],
        guideUrl: `${GUIDES}/features-drive-revenue`,
    },
    {
        id: 'onboarding-conversion',
        question: 'Which onboarding steps turn trials into paying customers?',
        description: 'Build a funnel, flag who pays, and find the steps that predict payment.',
        posthogData: 'Funnels',
        toolCategories: ['revenue'],
        guideUrl: `${GUIDES}/onboarding-conversion`,
    },
    {
        id: 'upsell-ready-accounts',
        question: 'Which accounts are ready to upsell?',
        description: "Compare product usage with each account's plan limits to flag accounts ready for an upgrade.",
        posthogData: 'Usage',
        toolCategories: ['revenue'],
        guideUrl: `${GUIDES}/upsell-ready-accounts`,
    },
    {
        id: 'pre-cancellation-behavior',
        question: 'What do customers do right before they cancel?',
        description: 'Pull in cancellations and look at the usage before each one to spot early warning signs.',
        posthogData: 'Events',
        toolCategories: ['revenue'],
        guideUrl: `${GUIDES}/pre-cancellation-behavior`,
    },
    {
        id: 'support-tickets-churn',
        question: 'Do support tickets predict churn?',
        description: 'Join usage, support tickets and cancellations to see which support issues come before churn.',
        posthogData: 'Usage',
        toolCategories: ['support'],
        guideUrl: `${GUIDES}/support-tickets-churn`,
    },
    {
        id: 'value-vs-engagement',
        question: 'Are our biggest accounts our happiest ones?',
        description: 'Map ARR against engagement to find large accounts that are at risk.',
        posthogData: 'Groups',
        toolCategories: ['crm'],
        guideUrl: `${GUIDES}/value-vs-engagement`,
    },
    {
        id: 'acquisition-channels-retention',
        question: 'Which channels bring customers who stick?',
        description: 'Rank marketing channels by the revenue they bring in after ad spend.',
        posthogData: 'Acquisition',
        toolCategories: ['revenue', 'ads'],
        guideUrl: `${GUIDES}/acquisition-channels-retention`,
    },
    {
        id: 'lead-scoring',
        question: "Which leads deserve the sales team's time?",
        description: "Score leads by product usage and list the most active ones sales hasn't contacted yet.",
        posthogData: 'Usage',
        toolCategories: ['crm'],
        guideUrl: `${GUIDES}/lead-scoring`,
    },
    {
        id: 'feature-revenue-impact',
        question: 'Did the feature we shipped move revenue?',
        description: 'Compare revenue for users who saw a feature flag or experiment against those who did not.',
        posthogData: 'Experiments',
        toolCategories: ['revenue'],
        guideUrl: `${GUIDES}/feature-revenue-impact`,
    },
]
