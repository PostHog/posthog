import type { BoxPlotDatum, FlameNode } from '@posthog/quill-charts'

import type { MetricsHistogramQueryResponse } from '~/queries/schema/schema-general'

import type { MetricsChartSeries } from 'products/metrics/frontend/components/metricsSeries'
import type { TrendsResultLike } from 'products/product_analytics/frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

import type { DataFrame } from './frame'

export interface PanelCategory {
    label: string
    value: number
}

export interface PanelFlow {
    source: string
    target: string
    value: number
}

export type PanelData =
    | { kind: 'series'; series: MetricsChartSeries[] }
    | { kind: 'trends'; results: TrendsResultLike[] }
    | { kind: 'categories'; categories: PanelCategory[] }
    | { kind: 'histogram'; histogram: MetricsHistogramQueryResponse }
    | { kind: 'flows'; flows: PanelFlow[] }
    | { kind: 'boxes'; labels: string[]; boxes: BoxPlotDatum[] }
    | { kind: 'flame'; roots: FlameNode[] }
    | { kind: 'frames'; frames: DataFrame[] }
