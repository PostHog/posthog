import { useEffect, useMemo, useState } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ErrorBoundary } from '~/layout/ErrorBoundary/ErrorBoundary'
import { SqlBoxPlot } from '~/queries/nodes/DataVisualization/Components/Charts/SqlBoxPlot'
import { getAutoBoxPlotSettings } from '~/queries/nodes/DataVisualization/Components/Charts/sqlBoxPlotAdapter'
import { SqlChart } from '~/queries/nodes/DataVisualization/Components/Charts/SqlChart'
import { SqlPieGraph } from '~/queries/nodes/DataVisualization/Components/Charts/SqlPieGraph'
import type { ChartSettings } from '~/queries/schema/schema-general'

import { HeatmapPanel } from 'products/metrics/frontend/panels/HeatmapPanel'
import { MetricsPanel } from 'products/metrics/frontend/panels/MetricsPanel'

import { chartType } from '../charts/chartTypes'
import { metricsDisplayOf, sqlDisplayOf, unitOf } from '../charts/displaySettings'
import { FlameGraphChart } from '../charts/FlameGraphChart'
import { FunnelStepsChart } from '../charts/FunnelStepsChart'
import { LogsViz } from '../charts/LogsViz'
import type { PanelData } from '../charts/panelData'
import { PathsFlowChart } from '../charts/PathsFlowChart'
import { RetentionChart } from '../charts/RetentionChart'
import { TracesViz } from '../charts/TracesViz'
import { logsOptionsOf, tracesOptionsOf } from '../charts/viewerProps'
import type { DashboardV2PanelApi } from '../generated/api.schemas'
import type { Panel } from '../spec'
import { DashboardV2PanelMessage } from './DashboardV2PanelMessage'
import { DashboardV2PanelSkeleton } from './DashboardV2PanelSkeleton'
import { useElementSize } from './useElementSize'

const NO_CHART_SETTINGS: ChartSettings = {}
const FILL = 'relative flex h-full min-h-0 w-full flex-col'
// The SQL charts paint their own surface colour. Inside a card the card is the surface, so clear it.
const SQL_FILL = `${FILL} [--color-bg-surface-primary:transparent]`

export interface DashboardV2PanelChartProps {
    panel: DashboardV2PanelApi
    data: PanelData | null
    error?: string | null
    onEditPanel?: (edit: (panel: Panel) => Panel) => void
}

interface PanelChartContentProps {
    panel: Panel
    data: PanelData
    width: number
    height: number
    onEditPanel: (edit: (panel: Panel) => Panel) => void
}

function PanelChartContent({ panel, data, width, height, onEditPanel }: PanelChartContentProps): JSX.Element {
    const type = panel.viz.type
    const boxPlotSettings = useMemo<ChartSettings>(
        () => (data.kind === 'rows' ? { boxPlot: getAutoBoxPlotSettings(data.columns) } : NO_CHART_SETTINGS),
        [data]
    )

    if (data.kind === 'axes' && (type === 'timeseries' || type === 'bar')) {
        return (
            <div className={SQL_FILL}>
                <SqlChart
                    xData={data.xData}
                    yData={data.yData}
                    visualizationType={sqlDisplayOf(panel)}
                    chartSettings={NO_CHART_SETTINGS}
                />
            </div>
        )
    }
    if (data.kind === 'axes' && type === 'pie') {
        return (
            <div className={SQL_FILL}>
                <SqlPieGraph
                    xData={data.xData}
                    yData={data.yData}
                    visualizationType={sqlDisplayOf(panel)}
                    chartSettings={NO_CHART_SETTINGS}
                />
            </div>
        )
    }
    if (data.kind === 'rows' && type === 'boxplot') {
        return (
            <div className={SQL_FILL}>
                <SqlBoxPlot
                    rows={data.rows}
                    columns={data.columns}
                    chartSettings={boxPlotSettings}
                    analyticsKey="dashboard-v2-panel"
                />
            </div>
        )
    }
    if (data.kind === 'series' && (type === 'timeseries' || type === 'stat' || type === 'gauge' || type === 'table')) {
        return (
            <div className={FILL}>
                <MetricsPanel
                    series={data.series}
                    display={metricsDisplayOf(panel)}
                    fallbackName={panel.title || 'Value'}
                />
            </div>
        )
    }
    if (data.kind === 'histogram' && type === 'heatmap') {
        return (
            <div className={FILL}>
                <HeatmapPanel response={data.histogram} unit={unitOf(panel)} />
            </div>
        )
    }
    if (data.kind === 'funnel' && type === 'bar') {
        return <FunnelStepsChart steps={data.steps} />
    }
    if (data.kind === 'retention' && type === 'retention') {
        return <RetentionChart cohorts={data.cohorts} />
    }
    if (data.kind === 'paths' && type === 'sankey') {
        return <PathsFlowChart links={data.links} />
    }
    if (data.kind === 'flame' && type === 'flamegraph') {
        return <FlameGraphChart roots={data.roots} height={height} />
    }
    if (data.kind === 'frames' && type === 'logs') {
        return (
            <LogsViz
                frames={data.frames}
                panel={panel}
                options={logsOptionsOf(panel)}
                width={width}
                height={height}
                onEditPanel={onEditPanel}
            />
        )
    }
    if (data.kind === 'frames' && type === 'traces') {
        return (
            <TracesViz
                frames={data.frames}
                panel={panel}
                options={tracesOptionsOf(panel)}
                width={width}
                height={height}
                onEditPanel={onEditPanel}
            />
        )
    }
    return (
        <DashboardV2PanelMessage
            title="This chart can't show this data"
            detail="Pick another chart type, or change what the panel measures."
        />
    )
}

export function DashboardV2PanelChart({ panel, data, error, onEditPanel }: DashboardV2PanelChartProps): JSX.Element {
    const { ref, width, height } = useElementSize<HTMLDivElement>()
    const [viewed, setViewed] = useState(panel as Panel)
    useEffect(() => setViewed(panel as Panel), [panel])
    const type = chartType(panel.viz.type)

    if (!type) {
        return (
            <DashboardV2PanelMessage
                title="This chart type isn't available yet"
                detail={`"${panel.viz.type}" charts don't show on this page yet.`}
            />
        )
    }
    if (!type.needsData) {
        const markdown = panel.viz.options?.markdown
        return (
            <div className="h-full overflow-auto">
                <LemonMarkdown>{typeof markdown === 'string' ? markdown : ''}</LemonMarkdown>
            </div>
        )
    }
    if (error) {
        return <DashboardV2PanelMessage title="Couldn't load this chart" detail={error} />
    }
    if (data === null) {
        return <DashboardV2PanelSkeleton type={panel.viz.type} />
    }

    return (
        <div ref={ref} className="h-full min-h-0 w-full min-w-0" data-attr="dashboard-v2-panel-chart">
            {width > 0 && height > 0 && (
                <ErrorBoundary key={panel.viz.type} className="h-full overflow-auto">
                    <PanelChartContent
                        panel={viewed}
                        data={data}
                        width={width}
                        height={height}
                        onEditPanel={onEditPanel ?? setViewed}
                    />
                </ErrorBoundary>
            )}
        </div>
    )
}
