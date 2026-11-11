import { ProductKey } from '~/queries/schema/schema-general'

export interface ProductPushPrompt {
    title: string
    facts: string[]
}

/**
 * A pushed product without a prompt gets no row in Today, because the sidebar's promo copy reads as an ad
 * next to the facts in that list. So every product in PRODUCT_PUSH_DISPLAY needs a prompt here too.
 * "Isn't set up" is what the campaign's usage check measures: the project has no intent for the product.
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
    [ProductKey.CONVERSATIONS]: {
        title: 'Support isn’t set up in this project yet',
        facts: ['People message you from inside your product, with their session history attached', 'Set up support'],
    },
    [ProductKey.ENDPOINTS]: {
        title: 'This project has no endpoints yet',
        facts: ['An endpoint turns a saved query into an API your app can call', 'Create an endpoint'],
    },
    [ProductKey.LLM_CLUSTERS]: {
        title: 'Clusters aren’t set up in this project yet',
        facts: ['Clusters group similar LLM conversations into patterns', 'Set up clusters'],
    },
    [ProductKey.LLM_EVALUATIONS]: {
        title: 'This project has no LLM evaluations yet',
        facts: ['Evaluations grade LLM outputs and flag regressions', 'Create an evaluation'],
    },
    [ProductKey.LLM_PROMPTS]: {
        title: 'This project doesn’t manage prompts in PostHog yet',
        facts: ['Each prompt is versioned, so you can change it without redeploying your app', 'Create a prompt'],
    },
    [ProductKey.MARKETING_ANALYTICS]: {
        title: 'Marketing analytics isn’t set up in this project yet',
        facts: ['It shows ad spend next to the signups each channel brought in', 'Set up marketing analytics'],
    },
    [ProductKey.MCP_ANALYTICS]: {
        title: 'MCP analytics isn’t set up in this project yet',
        facts: [
            'It shows which MCP tools agents call, how long each call takes and which calls fail',
            'Set up MCP analytics',
        ],
    },
    [ProductKey.NOTEBOOKS]: {
        title: 'No one has written a notebook in this project yet',
        facts: ['Notebooks hold live insights and recordings next to your notes', 'Create a notebook'],
    },
    [ProductKey.REPLAY_VISION]: {
        title: 'Replay vision isn’t set up in this project yet',
        facts: [
            'It reads your recordings and turns what happens in them into data you can query',
            'Set up replay vision',
        ],
    },
    [ProductKey.TOOLBAR]: {
        title: 'No one has launched the toolbar in this project yet',
        facts: ['The toolbar shows how each element performs, on your own site', 'Launch the toolbar'],
    },
    [ProductKey.POSTHOG_SLACK]: {
        title: 'PostHog isn’t in this organization’s Slack yet',
        facts: ['In Slack, your team can ask PostHog questions about your data', 'Add PostHog to Slack'],
    },
    [ProductKey.POSTHOG_GITHUB]: {
        title: 'GitHub isn’t connected to this organization yet',
        facts: ['With GitHub connected, PostHog can open pull requests with fixes', 'Connect GitHub'],
    },
    [ProductKey.POSTHOG_DESKTOP]: {
        title: 'No one in this organization uses PostHog Desktop yet',
        facts: ['Desktop runs AI agents that use your product data to ship changes', 'Get PostHog Desktop'],
    },
}
