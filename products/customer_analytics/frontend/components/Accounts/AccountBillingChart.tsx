import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    TimeSeriesBarChart,
    TimeSeriesComboChart,
    TimeSeriesLineChart,
    legendItemsFromSeries,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'

import { LineGraphProps } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import {
    SqlLineSeriesMeta,
    buildBarChartConfig,
    buildComboChartConfig,
    buildLineChartConfig,
    buildSeries,
    canRenderSqlBarGraph,
    canRenderSqlComboGraph,
    capYSeriesData,
} from '~/queries/nodes/DataVisualization/Components/Charts/sqlLineGraphAdapter'
import { useSqlChartModel } from '~/queries/nodes/DataVisualization/Components/Charts/useSqlChartModel'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { DataVisualizationNode, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AccountBillingLogicProps, accountBillingLogic } from './accountBillingLogic'
import { AccountBillingSeriesToggle } from './AccountBillingSeriesToggle'

const RENDERABLE_DISPLAY_TYPES = new Set<ChartDisplayType>([
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsStackedBar,
])

/** Series breakdowns are excluded because they need the full DataVisualization pipeline
 *  (seriesBreakdownLogic); those queries fall back to the embedded <Query>. */
export function canRenderBillingChart(query: Record<string, any> | null): query is DataVisualizationNode {
    return (
        query?.kind === NodeKind.DataVisualizationNode &&
        !!query.display &&
        RENDERABLE_DISPLAY_TYPES.has(query.display) &&
        !query.chartSettings?.seriesBreakdownColumn
    )
}

const handleChartError = (error: Error): void => {
    posthog.captureException(error, { scope: 'AccountBillingChart' })
}

function BillingChartByKind({
    chartProps,
    hiddenKeys,
}: {
    chartProps: LineGraphProps
    hiddenKeys: string[]
}): JSX.Element | null {
    if (canRenderSqlComboGraph(chartProps)) {
        return <BillingComboChart chartProps={chartProps} hiddenKeys={hiddenKeys} />
    }
    if (canRenderSqlBarGraph(chartProps)) {
        return <BillingBarChart chartProps={chartProps} hiddenKeys={hiddenKeys} />
    }
    return <BillingLineChart chartProps={chartProps} hiddenKeys={hiddenKeys} />
}

// One subcomponent per chart kind because useSqlChartModel's config type follows the builder it's given.
function BillingLineChart({
    chartProps,
    hiddenKeys,
}: {
    chartProps: LineGraphProps
    hiddenKeys: string[]
}): JSX.Element | null {
    const model = useSqlChartModel(chartProps, buildLineChartConfig)
    if (!model) {
        return null
    }
    return (
        <TimeSeriesLineChart<SqlLineSeriesMeta>
            series={model.series}
            labels={model.labels}
            theme={model.theme}
            config={{ ...model.config, legend: { ...model.config.legend, show: false, hiddenKeys } }}
            onError={handleChartError}
        />
    )
}

function BillingBarChart({
    chartProps,
    hiddenKeys,
}: {
    chartProps: LineGraphProps
    hiddenKeys: string[]
}): JSX.Element | null {
    const model = useSqlChartModel(chartProps, buildBarChartConfig)
    if (!model) {
        return null
    }
    return (
        <TimeSeriesBarChart<SqlLineSeriesMeta>
            series={model.series}
            labels={model.labels}
            theme={model.theme}
            config={{ ...model.config, legend: { ...model.config.legend, show: false, hiddenKeys } }}
            onError={handleChartError}
        />
    )
}

function BillingComboChart({
    chartProps,
    hiddenKeys,
}: {
    chartProps: LineGraphProps
    hiddenKeys: string[]
}): JSX.Element | null {
    const model = useSqlChartModel(chartProps, buildComboChartConfig)
    if (!model) {
        return null
    }
    return (
        <TimeSeriesComboChart<SqlLineSeriesMeta>
            series={model.series}
            labels={model.labels}
            theme={model.theme}
            config={{ ...model.config, legend: { ...model.config.legend, show: false, hiddenKeys } }}
            onError={handleChartError}
        />
    )
}

/**
 * Renders a saved billing insight's SQL chart directly via @posthog/quill-charts instead of the
 * embedded DataVisualization, so Customer analytics owns the per-series show/hide chips without
 * touching shared data-viz code. The shared pipeline is reused read-only — `dataVisualizationLogic`
 * for fetch + SQL-results→series parsing, the exported `useSqlChartModel`/config builders for the
 * render — so the chart matches what the insight renders elsewhere. Hidden series go into quill's
 * controlled `legend.hiddenKeys`: excluded from drawing and scales, the rest rescale into the
 * freed space.
 */
export function AccountBillingChart({
    logicProps,
    shortId,
    query,
    queryKey,
    variablesOverride,
}: {
    logicProps: AccountBillingLogicProps
    shortId: string
    query: DataVisualizationNode
    queryKey: string
    variablesOverride: Record<string, HogQLVariable> | null
}): JSX.Element {
    const billingLogic = accountBillingLogic(logicProps)
    const { hiddenSeriesKeysByShortId } = useValues(billingLogic)
    const { toggleHiddenSeriesKey } = useActions(billingLogic)

    const vizLogic = dataVisualizationLogic({
        key: queryKey,
        query,
        dataNodeCollectionId: queryKey,
        variablesOverride,
    })
    // Keeps the query's data logics alive across tab switches — they detach only on row collapse.
    useAttachedLogic(vizLogic, billingLogic)
    const { response, responseLoading, responseError, xData, yData, chartSettings, effectiveVisualizationType } =
        useValues(vizLogic)
    const theme = useChartTheme()

    const hiddenKeys = hiddenSeriesKeysByShortId[shortId] ?? []
    const chartProps: LineGraphProps = {
        xData,
        yData,
        visualizationType: effectiveVisualizationType,
        chartSettings,
        goalLines: chartSettings.goalLines,
    }
    // Derived from the same buildSeries output the chart draws, so chip keys and colors can't drift.
    const ySeriesData = capYSeriesData(yData)
    const chipItems = ySeriesData?.length
        ? legendItemsFromSeries(buildSeries(ySeriesData, effectiveVisualizationType), theme)
        : []

    let content: JSX.Element | null
    if (responseError) {
        content = <InsightErrorState query={query} title={responseError} excludeDetail />
    } else if (!response || responseLoading) {
        content = <LemonSkeleton className="h-full w-full" />
    } else if (!xData || chipItems.length === 0) {
        content = (
            <div className="flex flex-1 items-center justify-center text-secondary">
                No data for this date range. Try widening it.
            </div>
        )
    } else {
        content = <BillingChartByKind chartProps={chartProps} hiddenKeys={hiddenKeys} />
    }

    return (
        <div className="flex flex-col gap-1">
            {/* Quill charts fill their container, so the parent must have real dimensions. */}
            <div className="h-80 flex flex-col rounded bg-surface-primary overflow-hidden p-3">{content}</div>
            {chipItems.length > 1 && (
                <AccountBillingSeriesToggle
                    kind={logicProps.kind}
                    series={chipItems}
                    hiddenKeys={hiddenKeys}
                    onToggle={(seriesKey) => toggleHiddenSeriesKey(shortId, seriesKey, chipItems.length)}
                />
            )}
        </div>
    )
}
