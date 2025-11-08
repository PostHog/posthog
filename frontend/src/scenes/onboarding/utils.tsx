import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { type AvailableOnboardingProducts, ProductKey } from '~/types'

export const availableOnboardingProducts: AvailableOnboardingProducts = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        name: 'Product Analytics',
        description: 'Track events, trends, and user behavior to understand how people use your product',
        icon: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        url: urls.insights(),
        scene: Scene.SavedInsights,
    },
    [ProductKey.WEB_ANALYTICS]: {
        name: 'Web Analytics',
        description: 'Privacy-friendly analytics for your website with traffic, engagement, and conversion metrics',
        icon: 'IconPieChart',
        iconColor: 'rgb(54 196 111)',
        url: urls.webAnalytics(),
        scene: Scene.WebAnalytics,
    },
    [ProductKey.DATA_WAREHOUSE]: {
        name: 'Data Warehouse',
        description: 'Connect and query data from external sources alongside your PostHog data',
        icon: 'IconDatabase',
        iconColor: 'rgb(133 103 255)',
        breadcrumbsName: 'Data Warehouse',
        url: urls.dataPipelines('sources'),
        scene: Scene.DataPipelines,
    },
    [ProductKey.SESSION_REPLAY]: {
        name: 'Session Replay',
        description: 'Watch recordings of user sessions to see exactly how people interact with your product',
        icon: 'IconRewindPlay',
        iconColor: 'rgb(247 165 1)',
        url: urls.replay(),
        scene: Scene.Replay,
    },
    [ProductKey.FEATURE_FLAGS]: {
        name: 'Feature Flags',
        description: 'Roll out features gradually and toggle functionality without deploying new code',
        breadcrumbsName: 'Feature Flags',
        icon: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        url: urls.featureFlags(),
        scene: Scene.FeatureFlags,
    },
    [ProductKey.EXPERIMENTS]: {
        name: 'Experiments',
        description: 'Run A/B tests and multivariate experiments to optimize your product',
        breadcrumbsName: 'Experiments',
        icon: 'IconTestTube',
        iconColor: 'rgb(182 42 217)',
        url: urls.experiments(),
        scene: Scene.Experiments,
    },
    [ProductKey.SURVEYS]: {
        name: 'Surveys',
        description: 'Collect qualitative feedback directly from users with in-app surveys',
        icon: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        url: urls.surveys(),
        scene: Scene.Surveys,
    },
    [ProductKey.ERROR_TRACKING]: {
        name: 'Error Tracking',
        description: 'Monitor and debug errors and exceptions in your application',
        icon: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        url: urls.errorTracking(),
        scene: Scene.ErrorTracking,
    },
    [ProductKey.LLM_ANALYTICS]: {
        name: 'LLM Analytics',
        description: 'Track and analyze LLM usage, costs, and performance for AI-powered applications',
        icon: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        url: urls.llmAnalyticsDashboard(),
        scene: Scene.LLMAnalytics,
    },
}
