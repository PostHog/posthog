import { ProductKey } from '~/queries/schema/schema-general'

export type ProductNodeStatus = 'unlocked' | 'available' | 'coming_soon'

export interface ProductTreeNode {
    id: string
    productKey?: ProductKey
    label: string
    description: string
    shortDescription: string
    iconName: string
    color: string
    freeTier?: string
    category: 'analytics' | 'behavior' | 'features' | 'ai' | 'data' | 'core'
    featureFlag?: string
    comingSoon?: boolean
}

export interface ProductTreeEdge {
    source: string
    target: string
}

export const PRODUCT_NODES: ProductTreeNode[] = [
    // Core hub
    {
        id: 'events_core',
        label: 'Your Data',
        description: 'The foundation of everything. Once events flow in, the entire tree opens up.',
        shortDescription: 'Events flowing into PostHog',
        iconName: 'IconBolt',
        color: '#1D4AFF',
        category: 'core',
    },

    // Analytics branch
    {
        id: 'product_analytics',
        productKey: ProductKey.PRODUCT_ANALYTICS,
        label: 'Product analytics',
        description:
            'Understand how users interact with your product. Build funnels, track trends, analyze retention, and discover user paths through your app.',
        shortDescription: 'Track events, trends, and user behavior',
        iconName: 'IconGraph',
        color: 'rgb(47, 128, 250)',
        freeTier: '1M events/mo',
        category: 'analytics',
    },
    {
        id: 'web_analytics',
        productKey: ProductKey.WEB_ANALYTICS,
        label: 'Web analytics',
        description:
            'Privacy-friendly website analytics. Measure traffic, engagement, and conversion metrics without cookies.',
        shortDescription: 'Measure traffic and engagement',
        iconName: 'IconPieChart',
        color: 'rgb(54, 196, 111)',
        freeTier: '1M events/mo',
        category: 'analytics',
    },
    {
        id: 'revenue_analytics',
        productKey: ProductKey.REVENUE_ANALYTICS,
        label: 'Revenue analytics',
        description: 'Track revenue metrics, understand monetization, and connect product usage to business outcomes.',
        shortDescription: 'Connect product usage to revenue',
        iconName: 'IconTrending',
        color: 'rgb(245, 166, 35)',
        category: 'analytics',
        featureFlag: 'REVENUE_ANALYTICS',
        comingSoon: true,
    },
    {
        id: 'customer_analytics',
        productKey: ProductKey.CUSTOMER_ANALYTICS,
        label: 'Customer analytics',
        description: 'Deep-dive into customer segments, health scores, and lifecycle analysis.',
        shortDescription: 'Understand your customer segments',
        iconName: 'IconPeople',
        color: 'rgb(99, 184, 255)',
        category: 'analytics',
        featureFlag: 'CUSTOMER_ANALYTICS',
        comingSoon: true,
    },
    {
        id: 'marketing_analytics',
        productKey: ProductKey.MARKETING_ANALYTICS,
        label: 'Marketing analytics',
        description: 'Measure campaign performance, attribution, and marketing ROI across channels.',
        shortDescription: 'Track marketing performance',
        iconName: 'IconMegaphone',
        color: 'rgb(255, 135, 82)',
        category: 'analytics',
        featureFlag: 'WEB_ANALYTICS_MARKETING',
        comingSoon: true,
    },

    // Behavior branch
    {
        id: 'session_replay',
        productKey: ProductKey.SESSION_REPLAY,
        label: 'Session replay',
        description:
            'Watch real users navigate your app. See exactly what they see, including console logs, network requests, and click patterns.',
        shortDescription: 'Watch recordings of user sessions',
        iconName: 'IconRewindPlay',
        color: 'rgb(247, 165, 1)',
        freeTier: '15K recordings/mo',
        category: 'behavior',
    },
    {
        id: 'error_tracking',
        productKey: ProductKey.ERROR_TRACKING,
        label: 'Error tracking',
        description:
            'Catch exceptions and errors before users complain. See stack traces alongside session replays to debug faster.',
        shortDescription: 'Catch and fix bugs fast',
        iconName: 'IconWarning',
        color: 'rgb(235, 157, 42)',
        freeTier: '1M events/mo',
        category: 'behavior',
    },
    {
        id: 'heatmaps',
        productKey: ProductKey.HEATMAPS,
        label: 'Heatmaps',
        description: 'See where users click, scroll, and hover. Identify dead zones and engagement hotspots.',
        shortDescription: 'Visualize where users click',
        iconName: 'IconHeatmap',
        color: 'rgb(255, 100, 100)',
        category: 'behavior',
    },
    {
        id: 'surveys',
        productKey: ProductKey.SURVEYS,
        label: 'Surveys',
        description:
            'Ask users why they did what they did. Run NPS, PMF, and custom surveys targeted by user behavior.',
        shortDescription: 'Collect user feedback in-app',
        iconName: 'IconMessage',
        color: 'rgb(243, 84, 84)',
        freeTier: '250 responses/mo',
        category: 'behavior',
    },

    // Features branch
    {
        id: 'feature_flags',
        productKey: ProductKey.FEATURE_FLAGS,
        label: 'Feature flags',
        description:
            'Ship features safely with gradual rollouts. Target by user properties, percentage, or cohort. Kill switch instantly.',
        shortDescription: 'Ship features safely',
        iconName: 'IconToggle',
        color: 'rgb(48, 171, 198)',
        freeTier: '1M requests/mo',
        category: 'features',
    },
    {
        id: 'experiments',
        productKey: ProductKey.EXPERIMENTS,
        label: 'Experiments',
        description:
            'A/B test with statistical rigor. Bayesian analysis tells you which variant wins and when you have enough data.',
        shortDescription: 'Test changes and measure impact',
        iconName: 'IconTestTube',
        color: 'rgb(182, 42, 217)',
        freeTier: '1M requests/mo',
        category: 'features',
    },
    {
        id: 'early_access',
        productKey: ProductKey.EARLY_ACCESS_FEATURES,
        label: 'Early access',
        description: 'Let users opt into beta features. Manage feature previews and collect feedback from early adopters.',
        shortDescription: 'Manage beta feature access',
        iconName: 'IconRocket',
        color: 'rgb(130, 100, 255)',
        category: 'features',
    },

    // AI branch
    {
        id: 'llm_analytics',
        productKey: ProductKey.LLM_ANALYTICS,
        label: 'LLM analytics',
        description: 'Monitor your AI/LLM applications. Track costs, latency, token usage, and output quality.',
        shortDescription: 'Monitor AI/LLM applications',
        iconName: 'IconAI',
        color: 'rgb(182, 42, 217)',
        freeTier: '1M events/mo',
        category: 'ai',
    },

    // Data branch
    {
        id: 'data_warehouse',
        productKey: ProductKey.DATA_WAREHOUSE,
        label: 'Data warehouse',
        description:
            'Query external data sources alongside your PostHog data. Connect Stripe, Hubspot, Postgres, and more.',
        shortDescription: 'Query all your data in one place',
        iconName: 'IconDatabase',
        color: 'rgb(133, 103, 255)',
        freeTier: '1M synced rows/mo',
        category: 'data',
    },

    // Workflows
    {
        id: 'workflows',
        productKey: ProductKey.WORKFLOWS,
        label: 'Workflows',
        description: 'Automate user communication and internal processes. Trigger actions based on user behavior.',
        shortDescription: 'Automate actions and messaging',
        iconName: 'IconGear',
        color: 'rgb(100, 180, 120)',
        category: 'data',
        comingSoon: true,
    },
]

export const PRODUCT_EDGES: ProductTreeEdge[] = [
    // From core to main products
    { source: 'events_core', target: 'product_analytics' },
    { source: 'events_core', target: 'session_replay' },
    { source: 'events_core', target: 'feature_flags' },
    { source: 'events_core', target: 'data_warehouse' },
    { source: 'events_core', target: 'llm_analytics' },

    // Analytics branch
    { source: 'product_analytics', target: 'web_analytics' },
    { source: 'product_analytics', target: 'surveys' },
    { source: 'web_analytics', target: 'revenue_analytics' },
    { source: 'web_analytics', target: 'customer_analytics' },
    { source: 'web_analytics', target: 'marketing_analytics' },

    // Behavior branch
    { source: 'session_replay', target: 'error_tracking' },
    { source: 'session_replay', target: 'heatmaps' },

    // Features branch
    { source: 'feature_flags', target: 'experiments' },
    { source: 'feature_flags', target: 'early_access' },

    // Workflows from data warehouse
    { source: 'data_warehouse', target: 'workflows' },
]

export function getNodeCategory(category: ProductTreeNode['category']): { label: string; gradient: string } {
    switch (category) {
        case 'core':
            return { label: 'Foundation', gradient: 'from-blue-600 to-blue-400' }
        case 'analytics':
            return { label: 'Analytics', gradient: 'from-blue-500 to-cyan-400' }
        case 'behavior':
            return { label: 'Behavior', gradient: 'from-amber-500 to-orange-400' }
        case 'features':
            return { label: 'Features', gradient: 'from-cyan-500 to-teal-400' }
        case 'ai':
            return { label: 'AI engineering', gradient: 'from-purple-500 to-pink-400' }
        case 'data':
            return { label: 'Data', gradient: 'from-violet-500 to-indigo-400' }
    }
}
