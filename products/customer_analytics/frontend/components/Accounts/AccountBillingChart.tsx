import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    type ChartTheme,
    type LegendItem,
    type Series,
    TimeSeriesBarChart,
    TimeSeriesComboChart,
    TimeSeriesLineChart,
    legendItemsFromSeries,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { teamLogic } from 'scenes/teamLogic'

import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { DataVisualizationNode, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    type BillingChartProps,
    type BillingSeriesMeta,
    type BuildConfigArgs,
    buildBillingBarChartConfig,
    buildBillingComboChartConfig,
    buildBillingLineChartConfig,
    buildBillingSeries,
    canRenderBillingBarChart,
    canRenderBillingComboChart,
} from './accountBillingChartAdapter'
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

function chipItemsFromChartOwnSeries(
    yData: BillingChartProps['yData'],
    visualizationType: ChartDisplayType,
    theme: ChartTheme
): LegendItem[] {
    return yData?.length ? legendItemsFromSeries(buildBillingSeries(yData, visualizationType), theme) : []
}

interface BillingChartModel<TConfig> {
    series: Series<BillingSeriesMeta>[]
    labels: string[]
    theme: ChartTheme
    config: TConfig
}

/** Builds the quill series + config for one billing chart. Returns null until there's something to
 *  draw, so each renderer can bail without branching on half-built state. */
function useBillingChartModel<TConfig extends object>(
    { xData, yData, visualizationType, chartSettings, goalLines }: BillingChartProps,
    buildConfig: (args: BuildConfigArgs) => TConfig
): BillingChartModel<TConfig> | null {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()

    const series = useMemo(() => buildBillingSeries(yData, visualizationType), [yData, visualizationType])
    const config = useChartConfig(
        () =>
            xData ? buildConfig({ xData, yData, visualizationType, chartSettings, timezone, goalLines }) : undefined,
        [xData, yData, visualizationType, chartSettings, timezone, goalLines, buildConfig]
    )

    if (!xData || series.length === 0 || !config) {
        return null
    }
    return { series, labels: xData.data, theme, config }
}

function BillingChartByKind({
    chartProps,
    hiddenKeys,
}: {
    chartProps: BillingChartProps
    hiddenKeys: string[]
}): JSX.Element | null {
    if (canRenderBillingComboChart(chartProps)) {
        return <BillingComboChart chartProps={chartProps} hiddenKeys={hiddenKeys} />
    }
    if (canRenderBillingBarChart(chartProps)) {
        return <BillingBarChart chartProps={chartProps} hiddenKeys={hiddenKeys} />
    }
    return <BillingLineChart chartProps={chartProps} hiddenKeys={hiddenKeys} />
}

// One subcomponent per chart kind because useBillingChartModel's config type follows the builder it's given.
function BillingLineChart({
    chartProps,
    hiddenKeys,
}: {
    chartProps: BillingChartProps
    hiddenKeys: string[]
}): JSX.Element | null {
    const model = useBillingChartModel(chartProps, buildBillingLineChartConfig)
    if (!model) {
        return null
    }
    return (
        <TimeSeriesLineChart<BillingSeriesMeta>
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
    chartProps: BillingChartProps
    hiddenKeys: string[]
}): JSX.Element | null {
    const model = useBillingChartModel(chartProps, buildBillingBarChartConfig)
    if (!model) {
        return null
    }
    return (
        <TimeSeriesBarChart<BillingSeriesMeta>
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
    chartProps: BillingChartProps
    hiddenKeys: string[]
}): JSX.Element | null {
    const model = useBillingChartModel(chartProps, buildBillingComboChartConfig)
    if (!model) {
        return null
    }
    return (
        <TimeSeriesComboChart<BillingSeriesMeta>
            series={model.series}
            labels={model.labels}
            theme={model.theme}
            config={{ ...model.config, legend: { ...model.config.legend, show: false, hiddenKeys } }}
            onError={handleChartError}
        />
    )
}

/**
 * Renders a saved billing insight's chart directly via @posthog/quill-charts instead of the
 * embedded DataVisualization, so Customer analytics owns the per-series show/hide chips without
 * touching shared data-viz code. `dataVisualizationLogic` is still reused read-only for fetch +
 * SQL-results→series parsing; the series and chart config are built locally (see
 * `accountBillingChartAdapter`) so the SQL insight chart stays scoped to SQL insights. Hidden
 * series go into quill's controlled `legend.hiddenKeys`: excluded from drawing and scales, the
 * rest rescale into the freed space.
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
    const { ephemeralHiddenSeriesKeysByShortId } = useValues(billingLogic)
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

    const hiddenKeys = ephemeralHiddenSeriesKeysByShortId[shortId] ?? []
    const chartProps: BillingChartProps = {
        xData,
        yData,
        visualizationType: effectiveVisualizationType,
        chartSettings,
        goalLines: chartSettings.goalLines,
    }
    const chipItems = chipItemsFromChartOwnSeries(yData, effectiveVisualizationType, theme)

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
