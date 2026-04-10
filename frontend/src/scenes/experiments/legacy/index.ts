// Legacy experiment components re-exports
// These components support legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery)

// Logic
export { legacyExperimentModalsLogic } from './legacyExperimentModalsLogic'

// Metrics
export { TrendsMetricForm } from './metrics/TrendsMetricForm'
export { FunnelsMetricForm } from './metrics/FunnelsMetricForm'

// Shared Metrics
export { LegacySharedTrendsMetricForm } from './sharedMetrics/LegacySharedTrendsMetricForm'
export { LegacySharedFunnelsMetricForm } from './sharedMetrics/LegacySharedFunnelsMetricForm'

// Components
export { LegacyDataCollection } from './components/LegacyDataCollection'
export { LegacyExperimentDate } from './LegacyExperimentDate'
export { LegacyExperimentDates } from './LegacyExperimentDates'
export { LegacyExperimentHeader } from './components/LegacyExperimentHeader'
export { LegacyExperimentInfo } from './LegacyExperimentInfo'
export { LegacyExploreButton } from './components/LegacyExploreButton'
export { LegacyResultsQuery } from './components/LegacyResultsQuery'
export { LegacySummaryTable } from './components/LegacySummaryTable'
export { LegacyFunnelAttributionSelect } from './components/LegacyFunnelAttributionSelect'
export { LegacyFunnelConversionWindowFilter } from './components/LegacyFunnelConversionWindowFilter'
export { LegacyFunnelAggregationSelect } from './components/LegacyFunnelAggregationSelect'

// Calculations
export * from './calculations/legacyExperimentCalculations'

// Metrics View
export { LegacyMetricsView } from './metricsView/LegacyMetricsView'
export { LegacyChartModal } from './metricsView/LegacyChartModal'
export { LegacyDeltaChart } from './metricsView/LegacyDeltaChart'
export { LegacyChartEmptyState } from './metricsView/LegacyChartEmptyState'
export { LegacyErrorChecklist } from './metricsView/LegacyErrorChecklist'
export { LegacyMetricsChartLayout } from './metricsView/LegacyMetricsChartLayout'
export { LegacySignificanceHighlight } from './metricsView/LegacySignificanceHighlight'
export { LegacyTickPanel } from './metricsView/LegacyTickPanel'
export { LegacyVariantTooltip } from './metricsView/LegacyVariantTooltip'
export { LegacyWinningVariantText, LegacySignificanceText } from './metricsView/LegacyOverview'
export { LegacyVariantTag } from './components/LegacyVariantTag'
export * from './metricsView/legacyViolinUtils'

// Metrics View - Shared (Legacy)
export { LegacyChartLoadingState } from './metricsView/LegacyChartLoadingState'
export { LegacyGridLines } from './metricsView/LegacyGridLines'
export { LegacyMetricHeader } from './metricsView/LegacyMetricHeader'
export { LegacyMetricTitle } from './metricsView/LegacyMetricTitle'
export { useLegacyChartColors, LEGACY_COLORS } from './metricsView/legacyColors'
export * from './metricsView/legacyUtils'
