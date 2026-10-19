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
    // Sent to PostHog AI by the card's "Ask PostHog AI" button, followed by WAREHOUSE_QUESTION_PROMPT_SUFFIX.
    aiPrompt: string
    guideUrl: string
}

// Added to every question's prompt, so PostHog AI handles a missing source and ends with a saved insight.
export const WAREHOUSE_QUESTION_PROMPT_SUFFIX =
    "If a source this needs isn't connected yet, help me connect it first. Save the result as an insight."

const GUIDES = 'https://posthog.com/pocket-guides/data-stack'

export const WAREHOUSE_QUESTIONS: WarehouseQuestion[] = [
    {
        id: 'features-drive-revenue',
        question: 'Which features drive revenue?',
        description:
            'Join product usage to your revenue data to find the features that bring in the most revenue per user.',
        posthogData: 'Events',
        toolCategories: ['revenue'],
        aiPrompt:
            'Create an insight that ranks our product features by the revenue of the customers who use them. Join PostHog feature usage events to our revenue data (Stripe, Chargebee, Paddle or Recurly) by customer, and show revenue per user for each feature.',
        guideUrl: `${GUIDES}/features-drive-revenue`,
    },
    {
        id: 'onboarding-conversion',
        question: 'Which onboarding steps turn trials into paying customers?',
        description: 'Build a funnel, flag who pays, and find the steps that predict payment.',
        posthogData: 'Funnels',
        toolCategories: ['revenue'],
        aiPrompt:
            'Create an insight that shows which onboarding steps turn trials into paying customers. Build a funnel of our onboarding steps from PostHog events, flag which users went on to make a first payment in our revenue data (Stripe, Chargebee, Paddle or Recurly), and compare how often payers and non-payers completed each step.',
        guideUrl: `${GUIDES}/onboarding-conversion`,
    },
    {
        id: 'upsell-ready-accounts',
        question: 'Which accounts are ready to upsell?',
        description: "Compare product usage with each account's plan limits to flag accounts ready for an upgrade.",
        posthogData: 'Usage',
        toolCategories: ['revenue'],
        aiPrompt:
            "Create an insight that lists accounts ready to upsell. Compare each account's product usage in PostHog with the limits of its current plan in our revenue data (Stripe, Chargebee, Paddle or Recurly), and flag accounts that are consistently near or over their limits while still on a lower plan.",
        guideUrl: `${GUIDES}/upsell-ready-accounts`,
    },
    {
        id: 'pre-cancellation-behavior',
        question: 'What do customers do right before they cancel?',
        description: 'Pull in cancellations and look at the usage before each one to spot early warning signs.',
        posthogData: 'Events',
        toolCategories: ['revenue'],
        aiPrompt:
            "Create an insight that shows what customers do in the 30 days before they cancel. Pull cancellation dates from our revenue data (Stripe, Chargebee, Paddle or Recurly), look at each customer's PostHog activity in the 30 days before, and compare it with customers who stayed to find early warning signs.",
        guideUrl: `${GUIDES}/pre-cancellation-behavior`,
    },
    {
        id: 'support-tickets-churn',
        question: 'Do support tickets predict churn?',
        description: 'Join usage, support tickets and cancellations to see which support issues come before churn.',
        posthogData: 'Usage',
        toolCategories: ['support'],
        aiPrompt:
            'Create an insight that tests whether support tickets predict churn. Join PostHog usage, tickets and their topics from our support tool (Zendesk, Intercom, Freshdesk or Help Scout), and cancellations from our revenue data, then rank ticket topics by the revenue lost from customers who churned after raising them.',
        guideUrl: `${GUIDES}/support-tickets-churn`,
    },
    {
        id: 'value-vs-engagement',
        question: 'Are our biggest accounts our happiest ones?',
        description: 'Map ARR against engagement to find large accounts that are at risk.',
        posthogData: 'Groups',
        toolCategories: ['crm'],
        aiPrompt:
            "Create an insight that compares each account's ARR from our CRM (Salesforce, HubSpot, Pipedrive or Attio) with its engagement in PostHog, and flags high-ARR accounts with low engagement.",
        guideUrl: `${GUIDES}/value-vs-engagement`,
    },
    {
        id: 'acquisition-channels-retention',
        question: 'Which channels bring customers who stick?',
        description: 'Rank marketing channels by the revenue they bring in after ad spend.',
        posthogData: 'Acquisition',
        toolCategories: ['revenue', 'ads'],
        aiPrompt:
            'Create an insight that ranks our acquisition channels by the retained revenue of the customers they bring in. Use first-touch acquisition data from PostHog, revenue from our revenue tool (Stripe, Chargebee, Paddle or Recurly), and ad spend from our ad platforms (Google Ads, Meta Ads, LinkedIn Ads or TikTok Ads) to show retained revenue and CAC payback for each channel.',
        guideUrl: `${GUIDES}/acquisition-channels-retention`,
    },
    {
        id: 'lead-scoring',
        question: "Which leads deserve the sales team's time?",
        description: "Score leads by product usage and list the most active ones sales hasn't contacted yet.",
        posthogData: 'Usage',
        toolCategories: ['crm'],
        aiPrompt:
            "Create an insight that scores the leads in our CRM (Salesforce, HubSpot, Pipedrive or Attio) by their recent product usage in PostHog, and lists the most active leads that sales hasn't contacted yet.",
        guideUrl: `${GUIDES}/lead-scoring`,
    },
    {
        id: 'feature-revenue-impact',
        question: 'Did the feature we shipped move revenue?',
        description: 'Compare revenue for users who saw a feature flag or experiment against those who did not.',
        posthogData: 'Experiments',
        toolCategories: ['revenue'],
        aiPrompt:
            "Create an insight that measures whether a feature we shipped changed revenue. Ask me which feature flag or experiment to use, split users into those who saw it and those who didn't, then compare their revenue and retention from our revenue data (Stripe, Chargebee, Paddle or Recurly).",
        guideUrl: `${GUIDES}/feature-revenue-impact`,
    },
]
