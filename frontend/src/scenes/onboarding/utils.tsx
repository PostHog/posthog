import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { type AvailableOnboardingProducts, ProductKey } from '~/types'

export const availableOnboardingProducts: AvailableOnboardingProducts = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        name: 'Product Analytics',
        description: 'Understand what users do with funnels, trends, and retention analysis',
        icon: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        url: urls.insights(),
        scene: Scene.SavedInsights,
    },
    [ProductKey.WEB_ANALYTICS]: {
        name: 'Web Analytics',
        description: 'Track website traffic and conversions with GA4-style analytics',
        icon: 'IconPieChart',
        iconColor: 'rgb(54 196 111)',
        url: urls.webAnalytics(),
        scene: Scene.WebAnalytics,
    },
    [ProductKey.DATA_WAREHOUSE]: {
        name: 'Data Warehouse',
        description: 'Connect and query external data sources alongside your product data',
        icon: 'IconDatabase',
        iconColor: 'rgb(133 103 255)',
        breadcrumbsName: 'Data Warehouse',
        url: urls.dataPipelines('sources'),
        scene: Scene.DataPipelines,
    },
    [ProductKey.SESSION_REPLAY]: {
        name: 'Session Replay',
        description: 'Watch recordings of real user sessions to see exactly what happened',
        icon: 'IconRewindPlay',
        iconColor: 'rgb(247 165 1)',
        url: urls.replay(),
        scene: Scene.Replay,
    },
    [ProductKey.FEATURE_FLAGS]: {
        name: 'Feature Flags',
        description: 'Control feature rollouts and target specific users or groups',
        breadcrumbsName: 'Feature Flags',
        icon: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        url: urls.featureFlags(),
        scene: Scene.FeatureFlags,
    },
    [ProductKey.EXPERIMENTS]: {
        name: 'Experiments',
        description: 'Run A/B tests to see which features and changes perform best',
        breadcrumbsName: 'Experiments',
        icon: 'IconTestTube',
        iconColor: 'rgb(182 42 217)',
        url: urls.experiments(),
        scene: Scene.Experiments,
    },
    [ProductKey.SURVEYS]: {
        name: 'Surveys',
        description: 'Collect feedback from users with in-app surveys and forms',
        icon: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        url: urls.surveys(),
        scene: Scene.Surveys,
    },
    [ProductKey.ERROR_TRACKING]: {
        name: 'Error Tracking',
        description: 'Track and monitor errors to understand and fix issues faster',
        icon: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        url: urls.errorTracking(),
        scene: Scene.ErrorTracking,
    },
    [ProductKey.LLM_ANALYTICS]: {
        name: 'LLM Analytics',
        description: 'Monitor AI/LLM performance with traces, costs, and quality metrics',
        icon: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        url: urls.llmAnalyticsDashboard(),
        scene: Scene.LLMAnalytics,
    },
}
