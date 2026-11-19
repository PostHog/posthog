import { useEffect, useState } from 'react'

import { ErrorBoundary } from '~/layout/ErrorBoundary/ErrorBoundary'

import { HeatmapPanel } from 'products/metrics/frontend/panels/HeatmapPanel'

import { BoxPlotChart } from '../charts/BoxPlotChart'
import { CategoryBarChart } from '../charts/CategoryBarChart'
import { CategoryPieChart } from '../charts/CategoryPieChart'
import { chartType } from '../charts/chartTypes'
import { unitOf } from '../charts/displaySettings'
import { FlameGraphChart } from '../charts/FlameGraphChart'
import { FlowsChart } from '../charts/FlowsChart'
import { FunnelStepsChart } from '../charts/FunnelStepsChart'
import { LogsViz } from '../charts/LogsViz'
import { MetricsStyleChart } from '../charts/MetricsStyleChart'
import type { PanelData } from '../charts/panelData'
import { TextPanel } from '../charts/TextPanel'
import { TracesViz } from '../charts/TracesViz'
import { TrendsStyleChart } from '../charts/TrendsStyleChart'
import { logsOptionsOf, tracesOptionsOf } from '../charts/viewerProps'
import type { DashboardV2PanelApi } from '../generated/api.schemas'
import type { Panel } from '../spec'
import { DashboardV2PanelMessage } from './DashboardV2PanelMessage'
import { DashboardV2PanelSkeleton } from './DashboardV2PanelSkeleton'
import { useElementSize } from './useElementSize'

export interface DashboardV2PanelChartProps {
    panel: DashboardV2PanelApi
    data: PanelData | null
    error?: string | null
    timezone?: string
    onEditPanel?: (edit: (panel: Panel) => Panel) => void
}

interface PanelChartContentProps {
    panel: Panel
    data: PanelData
    width: number
    height: number
    timezone?: string
    onEditPanel: (edit: (panel: Panel) => Panel) => void
}

function PanelChartContent({ panel, data, width, height, timezone, onEditPanel }: PanelChartContentProps): JSX.Element {
    const type = panel.viz.type

    if (data.kind === 'trends' && type === 'timeseries') {
        return <TrendsStyleChart panel={panel} results={data.results} timezone={timezone} />
    }
    if (data.kind === 'series' && (type === 'timeseries' || type === 'stat' || type === 'gauge' || type === 'table')) {
        return <MetricsStyleChart panel={panel} series={data.series} />
    }
    if (data.kind === 'histogram' && type === 'heatmap') {
        return (
            <div className="relative flex h-full min-h-0 w-full flex-col">
                <HeatmapPanel response={data.histogram} unit={unitOf(panel)} />
            </div>
        )
    }
    if (data.kind === 'categories' && type === 'bar') {
        return panel.viz.options?.funnel ? (
            <FunnelStepsChart panel={panel} categories={data.categories} />
        ) : (
            <CategoryBarChart panel={panel} categories={data.categories} />
        )
    }
    if (data.kind === 'categories' && type === 'pie') {
        return <CategoryPieChart panel={panel} categories={data.categories} />
    }
    if (data.kind === 'flows' && type === 'sankey') {
        return <FlowsChart flows={data.flows} />
    }
    if (data.kind === 'boxes' && type === 'boxplot') {
        return <BoxPlotChart panel={panel} labels={data.labels} boxes={data.boxes} />
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

export function DashboardV2PanelChart({
    panel,
    data,
    error,
    timezone,
    onEditPanel,
}: DashboardV2PanelChartProps): JSX.Element {
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
        return <TextPanel markdown={typeof markdown === 'string' ? markdown : ''} />
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
                        timezone={timezone}
                        onEditPanel={onEditPanel ?? setViewed}
                    />
                </ErrorBoundary>
            )}
        </div>
    )
}
