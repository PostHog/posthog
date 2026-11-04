import { lazyWithPreload } from 'lib/utils/retryImport'

// Each renderer loads in its own chunk, so a scene ships only the node kinds it draws.
// A scene that draws a kind on first paint calls its `preload()` when the scene logic mounts.

export const InsightVizRenderer = lazyWithPreload(() =>
    import('~/queries/nodes/InsightViz/InsightViz').then((m) => ({ default: m.InsightViz }))
)

export const DataVisualizationRenderer = lazyWithPreload(() =>
    import('~/queries/nodes/DataVisualization/DataVisualization').then((m) => ({
        default: m.DataTableVisualization,
    }))
)

export const SavedInsightRenderer = lazyWithPreload(() =>
    import('~/queries/nodes/SavedInsight/SavedInsight').then((m) => ({ default: m.SavedInsight }))
)

export const WebOverviewRenderer = lazyWithPreload(() =>
    import('~/queries/nodes/WebOverview/WebOverview').then((m) => ({ default: m.WebOverview }))
)

export const MetricsQueryRenderer = lazyWithPreload(() =>
    import('products/metrics/frontend/nodes').then((m) => ({ default: m.MetricsQueryNode }))
)

export const MetricsHistogramQueryRenderer = lazyWithPreload(() =>
    import('products/metrics/frontend/nodes').then((m) => ({ default: m.MetricsHistogramQueryNode }))
)

export const EndpointsUsageOverviewRenderer = lazyWithPreload(() =>
    import('products/endpoints/frontend/nodes').then((m) => ({ default: m.EndpointsUsageOverviewNode }))
)

export const EndpointsUsageTrendsRenderer = lazyWithPreload(() =>
    import('products/endpoints/frontend/nodes').then((m) => ({ default: m.EndpointsUsageTrendsNode }))
)

export const MarketingAnalyticsOverviewRenderer = lazyWithPreload(() =>
    import('scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsOverview/MarketingAnalyticsOverview').then(
        (m) => ({ default: m.MarketingAnalyticsOverview })
    )
)

export const WebVitalsRenderer = lazyWithPreload(() =>
    import('~/queries/nodes/WebVitals/WebVitals').then((m) => ({ default: m.WebVitals }))
)

export const WebVitalsPathBreakdownRenderer = lazyWithPreload(() =>
    import('~/queries/nodes/WebVitals/WebVitalsPathBreakdown').then((m) => ({ default: m.WebVitalsPathBreakdown }))
)

export const HogDebugRenderer = lazyWithPreload(() =>
    import('scenes/debug/HogDebug').then((m) => ({ default: m.HogDebug }))
)

export const QueryEditorRenderer = lazyWithPreload(() =>
    import('~/queries/QueryEditor/QueryEditor').then((m) => ({ default: m.QueryEditor }))
)
