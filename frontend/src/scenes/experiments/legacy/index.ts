// Legacy experiment components re-exports
// These components support legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery)

// Metrics
export { LegacyMetricModal } from './metrics/LegacyMetricModal'
export { LegacyMetricSourceModal } from './metrics/LegacyMetricSourceModal'
export { LegacySharedMetricModal } from './metrics/LegacySharedMetricModal'
export { TrendsMetricForm } from './metrics/TrendsMetricForm'
export { FunnelsMetricForm } from './metrics/FunnelsMetricForm'

// Shared Metrics
export { LegacySharedTrendsMetricForm } from './sharedMetrics/LegacySharedTrendsMetricForm'
export { LegacySharedFunnelsMetricForm } from './sharedMetrics/LegacySharedFunnelsMetricForm'

// Components
export { LegacyExperimentHeader } from './components/LegacyExperimentHeader'
export { LegacyExperimentDate } from './LegacyExperimentDate'
export { LegacyExperimentDates } from './LegacyExperimentDates'
export { LegacyExperimentInfo } from './LegacyExperimentInfo'

// Calculations
export * from './calculations/legacyExperimentCalculations'

// Metrics View
export { MetricsViewLegacy } from './metricsView/MetricsViewLegacy'
export { ChartModal } from './metricsView/ChartModal'
export { DeltaChart } from './metricsView/DeltaChart'
export { LegacyErrorChecklist } from './metricsView/LegacyErrorChecklist'
export { MetricsChartLayout } from './metricsView/MetricsChartLayout'
export { SignificanceHighlight } from './metricsView/SignificanceHighlight'
export { TickPanel } from './metricsView/TickPanel'
export { VariantDeltaTimeseries } from './metricsView/VariantDeltaTimeseries'
export { VariantTooltip } from './metricsView/VariantTooltip'
export { ViolinPath } from './metricsView/ViolinPath'
export * from './metricsView/violinUtils'
