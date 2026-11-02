import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

export interface TodayExploreItem {
    product: string
    name: string
    description: string
    icon: FileSystemIconType
    sceneKey: Scene
    to: () => string
}

export const EXPLORE_ITEMS: TodayExploreItem[] = [
    {
        product: 'product_analytics',
        name: 'Product analytics',
        description: 'Charts from your events',
        icon: 'product_analytics',
        sceneKey: Scene.SavedInsights,
        to: () => urls.savedInsights(),
    },
    {
        product: 'session_replay',
        name: 'Session replay',
        description: 'Watch real user sessions',
        icon: 'session_replay',
        sceneKey: Scene.Replay,
        to: () => urls.replay(),
    },
    {
        product: 'feature_flags',
        name: 'Feature flags',
        description: 'Roll out changes safely',
        icon: 'feature_flag',
        sceneKey: Scene.FeatureFlags,
        to: () => urls.featureFlags(),
    },
    {
        product: 'ai_observability',
        name: 'AI observability',
        description: 'Trace LLM calls and cost',
        icon: 'llm_analytics',
        sceneKey: Scene.AIObservability,
        to: () => urls.aiObservabilityDashboard(),
    },
    {
        product: 'mcp_analytics',
        name: 'MCP analytics',
        description: 'Tool calls from agents',
        icon: 'mcp_analytics',
        sceneKey: Scene.MCPAnalytics,
        to: () => urls.mcpAnalytics(),
    },
    {
        product: 'error_tracking',
        name: 'Error tracking',
        description: 'Catch and fix exceptions',
        icon: 'error_tracking',
        sceneKey: Scene.ErrorTracking,
        to: () => urls.errorTracking(),
    },
    {
        product: 'experiments',
        name: 'Experiments',
        description: 'Test what a change does',
        icon: 'experiment',
        sceneKey: Scene.Experiments,
        to: () => urls.experiments(),
    },
    {
        product: 'web_analytics',
        name: 'Web analytics',
        description: 'Traffic and top pages',
        icon: 'web_analytics',
        sceneKey: Scene.WebAnalytics,
        to: () => urls.webAnalytics(),
    },
    {
        product: 'logs',
        name: 'Logs',
        description: 'Search your app logs',
        icon: 'logs',
        sceneKey: Scene.Logs,
        to: () => urls.logs(),
    },
]
