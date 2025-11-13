import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { type AvailableOnboardingProducts, ProductKey } from '~/types'

export const availableOnboardingProducts: AvailableOnboardingProducts = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        name: 'Product Analytics',
        icon: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        url: urls.insights(),
        scene: Scene.SavedInsights,
    },
    [ProductKey.WEB_ANALYTICS]: {
        name: 'Web Analytics',
        icon: 'IconPieChart',
        iconColor: 'rgb(54 196 111)',
        url: urls.webAnalytics(),
        scene: Scene.WebAnalytics,
    },
    [ProductKey.DATA_WAREHOUSE]: {
        name: 'Data Warehouse',
        icon: 'IconDatabase',
        iconColor: 'rgb(133 103 255)',
        breadcrumbsName: 'Data Warehouse',
        url: urls.dataPipelines('sources'),
        scene: Scene.DataPipelines,
    },
    [ProductKey.SESSION_REPLAY]: {
        name: 'Session Replay',
        icon: 'IconRewindPlay',
        iconColor: 'rgb(247 165 1)',
        url: urls.replay(),
        scene: Scene.Replay,
    },
    [ProductKey.FEATURE_FLAGS]: {
        name: 'Feature Flags',
        breadcrumbsName: 'Feature Flags',
        icon: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        url: urls.featureFlags(),
        scene: Scene.FeatureFlags,
    },
    [ProductKey.EXPERIMENTS]: {
        name: 'Experiments',
        breadcrumbsName: 'Experiments',
        icon: 'IconTestTube',
        iconColor: 'rgb(182 42 217)',
        url: urls.experiments(),
        scene: Scene.Experiments,
    },
    [ProductKey.SURVEYS]: {
        name: 'Surveys',
        icon: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        url: urls.surveys(),
        scene: Scene.Surveys,
    },
    [ProductKey.ERROR_TRACKING]: {
        name: 'Error Tracking',
        icon: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        url: urls.errorTracking(),
        scene: Scene.ErrorTracking,
    },
    [ProductKey.LLM_ANALYTICS]: {
        name: 'LLM Analytics',
        icon: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        url: urls.llmAnalyticsDashboard(),
        scene: Scene.LLMAnalytics,
    },
}
