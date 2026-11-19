import type { FlameNode } from '@posthog/quill-charts'

import type { AxisSeries, Column } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import type { MetricsHistogramQueryResponse, PathsLink } from '~/queries/schema/schema-general'

import type { MetricsChartSeries } from 'products/metrics/frontend/components/metricsSeries'
import type { RetentionCohortLike } from 'products/product_analytics/frontend/insights/retention/shared/retentionChartTransforms'

import type { DataFrame } from './frame'

export interface PanelFunnelStep {
    name: string
    count: number
}

export type PanelData =
    | { kind: 'axes'; xData: AxisSeries<string>; yData: AxisSeries<number | null>[] }
    | { kind: 'rows'; columns: Column[]; rows: unknown[][] }
    | { kind: 'series'; series: MetricsChartSeries[] }
    | { kind: 'histogram'; histogram: MetricsHistogramQueryResponse }
    | { kind: 'funnel'; steps: PanelFunnelStep[] }
    | { kind: 'retention'; cohorts: RetentionCohortLike[] }
    | { kind: 'paths'; links: PathsLink[] }
    | { kind: 'flame'; roots: FlameNode[] }
    | { kind: 'frames'; frames: DataFrame[] }
