import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { type AvailableOnboardingProducts } from '~/types'

// This is the order we'll use to display the products in the onboarding
export const availableOnboardingProducts: AvailableOnboardingProducts = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        name: 'Product Analytics',
        description: 'Track events, trends, and user behavior',
        icon: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        url: urls.insights(),
        scene: Scene.SavedInsights,
    },
    [ProductKey.WEB_ANALYTICS]: {
        name: 'Web Analytics',
        description: 'Measure traffic, engagement, and conversion metrics for your website',
        icon: 'IconPieChart',
        iconColor: 'rgb(54 196 111)',
        url: urls.webAnalytics(),
        scene: Scene.WebAnalytics,
    },
    [ProductKey.SESSION_REPLAY]: {
        name: 'Session Replay',
        description: 'Watch recordings of user sessions to debug issues faster',
        icon: 'IconRewindPlay',
        iconColor: 'rgb(247 165 1)',
        url: urls.replay(),
        scene: Scene.Replay,
    },
    [ProductKey.LLM_ANALYTICS]: {
        name: 'LLM Analytics',
        description: 'Monitor LLM usage, costs, and quality',
        icon: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        url: urls.llmAnalyticsDashboard(),
        scene: Scene.LLMAnalytics,
    },
    [ProductKey.DATA_WAREHOUSE]: {
        name: 'Data Warehouse',
        description: 'Query external data alongside your PostHog data',
        icon: 'IconDatabase',
        iconColor: 'rgb(133 103 255)',
        breadcrumbsName: 'Data Warehouse',
        url: urls.sources(),
        scene: Scene.Sources,
    },
    [ProductKey.FEATURE_FLAGS]: {
        name: 'Feature Flags',
        description: 'Ship features safely with gradual rollouts',
        breadcrumbsName: 'Feature Flags',
        icon: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        url: urls.featureFlags(),
        scene: Scene.FeatureFlags,
    },
    [ProductKey.EXPERIMENTS]: {
        name: 'Experiments',
        description: 'Test changes and measure what works',
        breadcrumbsName: 'Experiments',
        icon: 'IconTestTube',
        iconColor: 'rgb(182 42 217)',
        url: urls.experiments(),
        scene: Scene.Experiments,
    },
    [ProductKey.ERROR_TRACKING]: {
        name: 'Error Tracking',
        description: 'Catch and fix bugs before users complain',
        icon: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        url: urls.errorTracking(),
        scene: Scene.ErrorTracking,
    },
    [ProductKey.SURVEYS]: {
        name: 'Surveys',
        description: 'Ask users why they did what they did',
        icon: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        url: urls.surveys(),
        scene: Scene.Surveys,
    },
    [ProductKey.WORKFLOWS]: {
        name: 'Workflows',
        description: 'Automate user communication and internal processes',
        icon: 'IconGear',
        iconColor: 'var(--color-product-workflows-light)',
        url: urls.workflows(),
        scene: Scene.Workflows,
    },
}
