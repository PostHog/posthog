import clsx from 'clsx'
import { BindLogic, BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { createXAxisTickCallback } from '@posthog/quill-charts'

import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { getResultMenuPoint, isResultMenuContextMenu, replayAsClick } from 'lib/components/ResultMenu/resultMenuTrigger'
import { PART_OF_WHOLE_DISPLAY_TYPES } from 'lib/constants'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    AnyResponseType,
    DashboardFilter,
    VisualizationNode,
    HogQLQuery,
    HogQLQueryResponse,
    HogQLVariable,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { shouldQueryBeAsync } from '~/queries/utils'
import { ChartDisplayType, ExportContext, ExporterFormat, InsightLogicProps } from '~/types'

import { alertsToThresholdGoalLines, insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import { BIChartAxisControls } from 'products/business_intelligence/frontend/BIChartAxisControls'
import { getBIChartDateAxis } from 'products/business_intelligence/frontend/biChartDateAxis'
import { BIChartYearLabels } from 'products/business_intelligence/frontend/BIChartYearLabels'
import { BIComparisonSummary } from 'products/business_intelligence/frontend/BIComparisonSummary'
import { getBIChartRecord } from 'products/business_intelligence/frontend/biDrilldown'
import { biDrilldownLogic } from 'products/business_intelligence/frontend/biDrilldownLogic'
import { BIDrilldownMenu } from 'products/business_intelligence/frontend/BIDrilldownMenu'
import { BIDrilldownModal } from 'products/business_intelligence/frontend/BIDrilldownModal'
import { getBIResultDimensions } from 'products/business_intelligence/frontend/biEditorTypes'
import { createBIMemberFormatter } from 'products/business_intelligence/frontend/biMemberAliases'
import { BIPaneCharts } from 'products/business_intelligence/frontend/BIPaneCharts'
import { BIPivotTable } from 'products/business_intelligence/frontend/BIPivotTable'
import { getBIVisualizationSource } from 'products/business_intelligence/frontend/biQueryResults'
import { BIScatterGraph } from 'products/business_intelligence/frontend/BIScatterGraph'
import { isBIPivotTable } from 'products/business_intelligence/frontend/biTableLayout'
import { HogQLBoldNumber } from 'products/product_analytics/frontend/insights/shared/BoldNumber/BoldNumber'

import { DataNodeLogicProps, dataNodeLogic } from '../DataNode/dataNodeLogic'
import { DateRange } from '../DataNode/DateRange'
import { ElapsedTime } from '../DataNode/ElapsedTime'
import { Reload } from '../DataNode/Reload'
import { QueryFeature } from '../DataTable/queryFeatures'
import { PartOfWholeChart } from './Components/Charts/PartOfWholeChart'
import { SqlBoxPlot } from './Components/Charts/SqlBoxPlot'
import { isSqlChartVisualizationType, SqlChart } from './Components/Charts/SqlChart'
import { getSeriesKey } from './Components/Charts/sqlLineGraphAdapter'
import { SqlMetricCard } from './Components/Charts/SqlMetricCard'
import { partOfWholeChartData } from './Components/Charts/sqlPieGraphAdapter'
import { SqlScatterGraph } from './Components/Charts/SqlScatterGraph'
import { TwoDimensionalHeatmap } from './Components/Heatmap/TwoDimensionalHeatmap'
import { seriesBreakdownLogic } from './Components/seriesBreakdownLogic'
import { SideBar } from './Components/SideBar'
import { Table } from './Components/Table'
import { TableDisplay } from './Components/TableDisplay'
import { AddVariableButton } from './Components/Variables/AddVariableButton'
import { variableModalLogic } from './Components/Variables/variableModalLogic'
import { VariablesForInsight } from './Components/Variables/Variables'
import { VariablesLogicProps, variablesLogic } from './Components/Variables/variablesLogic'
import { conditionalFormattingColor } from './conditionalFormatting'
import { DataVisualizationLogicProps, SideBarTab, dataVisualizationLogic } from './dataVisualizationLogic'
import { displayLogic } from './displayLogic'
import { applyDataVisualizationQueryUpdate } from './queryUpdateUtils'

export interface DataTableVisualizationProps {
    uniqueKey?: string | number
    query: VisualizationNode
    setQuery: (query: VisualizationNode) => void
    context?: QueryContext<VisualizationNode>
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
    editMode?: boolean
    readOnly?: boolean
    embedded?: boolean
    inSharedMode?: boolean
    exportContext?: ExportContext
    /** Dashboard variables to override the ones in the query */
    filtersOverride?: DashboardFilter | null
    variablesOverride?: Record<string, HogQLVariable> | null
    /** Attach ourselves to another logic, such as the scene logic */
    attachTo?: BuiltLogic | LogicWrapper
}

let uniqueNode = 0

export function DataTableVisualization({
    uniqueKey,
    query,
    setQuery,
    context,
    cachedResults,
    readOnly,
    variablesOverride,
    filtersOverride,
    attachTo,
    editMode,
    embedded,
    inSharedMode,
}: DataTableVisualizationProps): JSX.Element {
    const [key] = useState(`DataVisualizationNode.${uniqueKey ?? uniqueNode++}`)
    const queryRef = useRef(query)
    queryRef.current = query

    const insightProps: InsightLogicProps<VisualizationNode> = context?.insightProps || {
        dashboardItemId: `new-AdHoc.${key}`,
        query,
        setQuery,
        dataNodeCollectionId: key,
    }

    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeCollectionId = insightVizDataCollectionId(insightProps, key)
    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        loadQueue: context?.loadQueue,
        key: vizKey,
        query,
        dashboardId: insightProps.dashboardId,
        dataNodeCollectionId,
        loadPriority: insightProps.loadPriority,
        retainResponseOnUnmount: insightProps.retainResponseOnUnmount,
        editMode,
        setQuery: (setter) => {
            applyDataVisualizationQueryUpdate(queryRef, setter, setQuery)
        },
        cachedResults,
        variablesOverride: variablesOverride ?? insightProps.variablesOverride,
        filtersOverride: filtersOverride ?? insightProps.filtersOverride,
        limitContext: context?.limitContext,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        loadQueue: context?.loadQueue,
        query: getBIVisualizationSource(query),
        retainResponseOnUnmount: insightProps.retainResponseOnUnmount,
        key: vizKey,
        cachedResults,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId,
        variablesOverride: variablesOverride ?? insightProps.variablesOverride,
        filtersOverride: filtersOverride ?? insightProps.filtersOverride,
        limitContext: context?.limitContext,
    }

    // The `as unknown as InsightLogicProps` below is smelly, but it's required because Kea logics can't be generic
    const { exportContext } = useValues(insightDataLogic(insightProps as unknown as InsightLogicProps))

    const { loadData } = useActions(dataVisualizationLogic(dataVisualizationLogicProps))

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: readOnly ?? false,
        dashboardId: insightProps.dashboardId,
        sourceQuery: query,
        setQuery: setQuery,
        onUpdate: (query: VisualizationNode) => {
            const source = getBIVisualizationSource(query)
            loadData(shouldQueryBeAsync(source) ? 'force_async' : 'force_blocking', undefined, source)
        },
    }

    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), attachTo)
    useAttachedLogic(dataVisualizationLogic(dataVisualizationLogicProps), attachTo)
    useAttachedLogic(displayLogic({ key: dataVisualizationLogicProps.key }), attachTo)
    useAttachedLogic(variablesLogic(variablesLogicProps), attachTo)

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                        <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <InternalDataTableVisualization
                                uniqueKey={key}
                                query={query}
                                setQuery={setQuery}
                                context={context}
                                cachedResults={cachedResults}
                                readOnly={readOnly}
                                exportContext={exportContext}
                                editMode={editMode}
                                embedded={embedded}
                                inSharedMode={inSharedMode}
                                filtersOverride={filtersOverride ?? insightProps.filtersOverride}
                                variablesOverride={variablesOverride ?? insightProps.variablesOverride}
                            />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function InternalDataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const { readOnly } = props
    const settingsPanel = props.context?.visualizationSettingsPanel

    const {
        query,
        effectiveVisualizationType,
        showResultControls,
        sourceFeatures,
        response,
        responseLoading,
        responseError,
        queryCancelled,
        isChartSettingsPanelOpen,
        xData,
        yData,
        columns,
        chartSettings,
        conditionalFormattingRules,
        hogVm,
        hogVmLoadFailed,
        dashboardId,
        dataVisualizationProps,
        presetChartHeight: scenePresetChartHeight,
    } = useValues(dataVisualizationLogic)

    const { isDarkModeOn } = useValues(themeLogic)
    const columnTypes = useMemo(() => new Map(columns.map((column) => [column.name, column.type.name])), [columns])

    const presetChartHeight =
        !props.embedded &&
        scenePresetChartHeight &&
        !(query.kind === NodeKind.BIVisualizationNode && props.context?.visualizationSettingsPanel)
    const drilldownProps = {
        key: dataVisualizationProps.key,
        query,
        filtersOverride: props.filtersOverride,
        variablesOverride: props.variablesOverride,
        onFilterDashboard: !props.inSharedMode ? props.context?.onSelectBIMark : undefined,
        isDashboardFilterSelected: !props.inSharedMode ? props.context?.isBIMarkActiveFilter : undefined,
        getDashboardFilterUrl: !props.inSharedMode ? props.context?.getBIMarkDashboardUrl : undefined,
    }
    const drilldownLogic = biDrilldownLogic(drilldownProps)
    const { inspect: inspectResult, setInteraction, close: closeResultMenu } = useActions(drilldownLogic)
    const resultMenuTriggerRef = useRef<HTMLDivElement>(null)
    const inspectedPoint = useRef(false)
    const replayingClick = useRef(false)
    const inspect = useCallback(
        (record: Record<string, unknown>): void => {
            inspectedPoint.current = true
            inspectResult(record)
        },
        [inspectResult]
    )
    const isQuerySnapshot = query.kind === NodeKind.BIVisualizationNode && !!query.config.querySnapshot
    const canDrill = query.kind === NodeKind.BIVisualizationNode && !isQuerySnapshot && !props.inSharedMode
    const resultMenu = canDrill && !!props.context?.dashboardResultMenu

    const { seriesBreakdownData, chartData } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { goalLines } = useValues(displayLogic)

    // Overlay alert threshold bounds on the chart, like trends does — only when rendering a saved
    // insight (the SQL editor and other unsaved contexts have no alerts to show). Deliberately maps
    // alerts directly instead of using the alertThresholdLines selector: that selector gates on the
    // trends-only showAlertThresholdLines viz setting, which VisualizationNode doesn't have, so
    // going through it would hide the lines on SQL charts entirely.
    const alertsInsightProps = (props.context?.insightProps as InsightLogicProps | undefined) ?? {
        dashboardItemId: undefined,
    }
    const { insight } = useValues(insightLogic(alertsInsightProps))
    const { alerts } = useValues(
        insightAlertsLogic({
            insightId: insight?.id ?? 0,
            insightLogicProps: alertsInsightProps,
            deferInitialAlertsLoad: !insight?.id,
        })
    )
    const alertThresholdLines = useMemo(
        () => (insight?.id ? alertsToThresholdGoalLines(alerts) : []),
        [insight?.id, alerts]
    )
    const paneGoalLines = useMemo(() => [...alertThresholdLines, ...goalLines], [alertThresholdLines, goalLines])
    const biConfig = query.kind === NodeKind.BIVisualizationNode ? query.config : undefined
    const paneConfig = useMemo(
        () => (biConfig ? { ...biConfig, chartType: effectiveVisualizationType } : undefined),
        [biConfig, effectiveVisualizationType]
    )

    const { toggleChartSettingsPanel, setSideBarTab } = useActions(dataVisualizationLogic)

    const { queryId, pollResponse } = useValues(dataNodeLogic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery, props.query] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    const { timezone } = useValues(teamLogic)
    const dateBucket =
        query.kind === NodeKind.BIVisualizationNode
            ? getBIResultDimensions(query.config).find(({ column }) => column === xData?.column.name)?.field.dateBucket
            : undefined
    const showYearLabels =
        query.kind === NodeKind.BIVisualizationNode &&
        (xData?.column.type.name === 'DATE' || xData?.column.type.name === 'DATETIME') &&
        dateBucket !== 'year' &&
        !chartSettings.xAxisDateFormat &&
        effectiveVisualizationType !== ChartDisplayType.ActionsBarValue &&
        chartSettings.showXAxisTicks !== false
    const dateAxis = useMemo(
        () => (showYearLabels && xData ? getBIChartDateAxis(xData.data, timezone, dateBucket) : undefined),
        [showYearLabels, xData, timezone, dateBucket]
    )
    const dateMargins = useMemo(
        () => (showYearLabels ? { bottom: chartSettings.xAxisLabel ? 76 : 54 } : undefined),
        [showYearLabels, chartSettings.xAxisLabel]
    )

    const columnNames = useMemo(() => columns.map((column) => column.name), [columns])

    const controlSize = query.kind === NodeKind.BIVisualizationNode ? 'xsmall' : 'small'

    const isDateXAxis = xData?.column.type.name === 'DATE' || xData?.column.type.name === 'DATETIME'

    const sqlChartData = useMemo(() => {
        if (!isSqlChartVisualizationType(effectiveVisualizationType)) {
            return null
        }
        const { xData: chartXData, yData: chartYData } = chartData
        const xDimension = biConfig
            ? getBIResultDimensions(biConfig).find(({ column }) => column === chartXData?.column.name)
            : undefined
        const aliasFormatter = biConfig && xDimension ? createBIMemberFormatter(biConfig, xDimension.field) : undefined
        const fallbackTickFormatter = aliasFormatter
            ? (dateAxis?.tickFormatter ??
              (isDateXAxis
                  ? createXAxisTickCallback({ allDays: chartXData?.data ?? [], timezone, interval: dateBucket })
                  : undefined))
            : undefined
        return {
            xData: chartXData,
            yData: chartYData,
            labelFormatter: aliasFormatter,
            xAxis: aliasFormatter
                ? {
                      ...dateAxis,
                      tickFormatter: (value: string, index: number): string | null => {
                          const label = aliasFormatter(value)
                          return label !== value
                              ? label
                              : fallbackTickFormatter
                                ? fallbackTickFormatter(value, index)
                                : value
                      },
                  }
                : dateAxis,
        }
    }, [effectiveVisualizationType, chartData, biConfig, dateAxis, isDateXAxis, timezone, dateBucket])

    const pieDisplayData = useMemo(() => {
        if (!PART_OF_WHOLE_DISPLAY_TYPES.includes(effectiveVisualizationType)) {
            return null
        }
        const pieData = partOfWholeChartData(seriesBreakdownData, xData, yData)
        const pieDimension =
            query.kind === NodeKind.BIVisualizationNode
                ? getBIResultDimensions(query.config).find(
                      ({ column }) => column === (chartSettings.seriesBreakdownColumn ?? pieData.xData?.column.name)
                  )
                : undefined
        const aliasLabels = new Map<string, string>()
        const records = new Map<string, Record<string, unknown>>()
        let pieXData = pieData.xData
        let pieYData = pieData.yData
        const memberFormatter =
            query.kind === NodeKind.BIVisualizationNode && pieDimension
                ? createBIMemberFormatter(query.config, pieDimension.field)
                : undefined
        if (query.kind === NodeKind.BIVisualizationNode) {
            if (pieData.yData.every((series) => 'breakdownValue' in series)) {
                pieYData = pieData.yData.map((series) => {
                    const key = JSON.stringify([series.breakdownValue, series.name])
                    aliasLabels.set(key, series.settings?.display?.label ?? series.name)
                    records.set(key, getBIChartRecord(query, '', undefined, series.breakdownValue))
                    return { ...series, name: key }
                })
            } else if (pieXData && pieData.yData.length === 1) {
                pieXData = {
                    ...pieXData,
                    data: pieXData.data.map((value) => {
                        const key = JSON.stringify(value ?? null)
                        aliasLabels.set(
                            key,
                            memberFormatter
                                ? memberFormatter(value)
                                : value == null || value === ''
                                  ? '[No value]'
                                  : String(value)
                        )
                        records.set(key, { [pieData.xData!.column.name]: value })
                        return key
                    }),
                }
            }
        }

        return {
            xData: pieXData,
            yData: pieYData,
            labelFormatter: aliasLabels.size ? (label: string): string => aliasLabels.get(label) ?? label : undefined,
            records,
        }
    }, [effectiveVisualizationType, seriesBreakdownData, xData, yData, query, chartSettings.seriesBreakdownColumn])

    let component: JSX.Element | null = null

    if (responseError) {
        component = (
            <div className="rounded bg-surface-primary relative flex flex-1 flex-col p-2">
                <InsightErrorState
                    query={props.query}
                    excludeDetail
                    title={
                        queryCancelled
                            ? 'The query was cancelled'
                            : response && 'error' in response
                              ? (response as any).error
                              : responseError
                    }
                />
            </div>
        )
    } else if (!response || responseLoading) {
        // TODO(@Gilbert09): Better loading support for all components - e.g. using the `loading` param of `Table`
        component = (
            <div className="flex flex-col flex-1 justify-center items-center bg-surface-primary h-full">
                <StatelessInsightLoadingState queryId={queryId} pollResponse={pollResponse} />
            </div>
        )
    } else if (
        query.kind === NodeKind.BIVisualizationNode &&
        'results' in response &&
        Array.isArray(response.results) &&
        response.results.length === 0
    ) {
        component = (
            <div className="flex flex-1 items-center justify-center p-4 text-secondary">
                No results match these filters.
            </div>
        )
    } else if (
        query.kind === NodeKind.BIVisualizationNode &&
        getBIResultDimensions(query.config).some(({ column }) => !columns.some((result) => result.name === column))
    ) {
        component = (
            <LemonBanner type="warning">
                The returned columns do not match this worksheet. Run the query again or check the selected fields.
            </LemonBanner>
        )
    } else if (isQuerySnapshot && effectiveVisualizationType === ChartDisplayType.TwoDimensionalHeatmap) {
        component = (
            <LemonBanner type="info">Query snapshots do not support pivots. Choose another chart type.</LemonBanner>
        )
    } else if (
        query.kind === NodeKind.BIVisualizationNode &&
        (isBIPivotTable(query.config) ||
            (query.config.compareFilter?.compare &&
                [ChartDisplayType.ActionsTable, ChartDisplayType.BoldNumber, ChartDisplayType.Metric].includes(
                    effectiveVisualizationType
                )))
    ) {
        const resultProps = {
            config: query.config,
            columns: columns.map((column) => column.name),
            results: 'results' in response && Array.isArray(response.results) ? response.results : [],
            chartSettings,
            onInspect: canDrill ? inspect : undefined,
        }
        component = isBIPivotTable(query.config) ? (
            <BIPivotTable
                {...resultProps}
                embedded={props.embedded}
                formattingLoadFailed={hogVmLoadFailed}
                cellBackground={(record, column) =>
                    conditionalFormattingColor(
                        conditionalFormattingRules,
                        hogVm?.execHog,
                        column,
                        columnTypes.get(column) ?? 'UNKNOWN',
                        record[column],
                        isDarkModeOn
                    )
                }
            />
        ) : (
            <BIComparisonSummary {...resultProps} card={effectiveVisualizationType !== ChartDisplayType.ActionsTable} />
        )
    } else if (
        query.kind === NodeKind.BIVisualizationNode &&
        query.config.panes?.fields.length &&
        isSqlChartVisualizationType(effectiveVisualizationType)
    ) {
        component = (
            <BIPaneCharts
                config={paneConfig!}
                settings={chartSettings}
                columns={columns}
                rows={'results' in response && Array.isArray(response.results) ? response.results : []}
                goalLines={paneGoalLines}
                onInspect={canDrill ? inspect : undefined}
            />
        )
    } else if (effectiveVisualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <Table
                uniqueKey={props.uniqueKey}
                query={query}
                context={props.context}
                cachedResults={props.cachedResults as HogQLQueryResponse | undefined}
                embedded={props.embedded}
                onInspect={canDrill ? inspect : undefined}
            />
        )
    } else if (sqlChartData) {
        const { xData: _xData, yData: _yData } = sqlChartData
        component = (
            <BindLogic logic={insightLogic} props={alertsInsightProps}>
                <SqlChart
                    className="p-3"
                    {...sqlChartData}
                    visualizationType={effectiveVisualizationType}
                    chartSettings={chartSettings}
                    dashboardId={dashboardId}
                    goalLines={[...alertThresholdLines, ...goalLines]}
                    insightNumericId={insight?.id || 'new'}
                    showAnnotations={!props.inSharedMode && isDateXAxis && chartSettings.showAnnotations === true}
                    presetChartHeight={presetChartHeight}
                    embedded={props.embedded}
                    directPointClick={canDrill}
                    margins={dateMargins}
                    onPointClick={
                        canDrill
                            ? (seriesKey, dataIndex) => {
                                  const series = _yData.find(
                                      (series, index) => getSeriesKey(series, index) === seriesKey
                                  )
                                  if (_xData) {
                                      inspect(
                                          getBIChartRecord(
                                              query,
                                              _xData.column.name,
                                              _xData.data[dataIndex],
                                              series && 'breakdownValue' in series ? series.breakdownValue : undefined
                                          )
                                      )
                                  }
                              }
                            : undefined
                    }
                    pointClickHint={canDrill ? 'Click to explore this result' : undefined}
                >
                    {showYearLabels && <BIChartYearLabels timezone={timezone} />}
                    {query.kind === NodeKind.BIVisualizationNode && props.editMode && props.context?.onEditBIAxis && (
                        <BIChartAxisControls onEdit={props.context.onEditBIAxis} />
                    )}
                </SqlChart>
            </BindLogic>
        )
    } else if (pieDisplayData) {
        component = (
            <PartOfWholeChart
                className="p-3"
                {...pieDisplayData}
                onSliceClick={
                    canDrill
                        ? ({ series }) => {
                              const record = pieDisplayData.records.get(series.key)
                              if (record) {
                                  inspect(record)
                              }
                          }
                        : undefined
                }
                visualizationType={effectiveVisualizationType}
                chartSettings={chartSettings}
                presetChartHeight={presetChartHeight}
            />
        )
    } else if (effectiveVisualizationType === ChartDisplayType.ScatterPlot) {
        // Both axes are continuous, so a scatter reads the x column's own values rather than the
        // breakdown path's categorical labels (which dedupe x — fatal for a point cloud).
        component =
            query.kind === NodeKind.BIVisualizationNode ? (
                <BIScatterGraph
                    query={query}
                    columns={columnNames}
                    rows={'results' in response && Array.isArray(response.results) ? response.results : []}
                    chartKey={dataVisualizationProps.key}
                    onKeepOnly={props.editMode && !props.inSharedMode ? props.context?.onKeepBISelection : undefined}
                    onInspect={canDrill ? inspect : undefined}
                    className="p-3"
                    xData={xData}
                    yData={yData}
                    chartSettings={chartSettings}
                    presetChartHeight={presetChartHeight}
                />
            ) : (
                <SqlScatterGraph
                    className="p-3"
                    xData={xData}
                    yData={yData}
                    chartSettings={chartSettings}
                    presetChartHeight={presetChartHeight}
                />
            )
    } else if (effectiveVisualizationType === ChartDisplayType.BoxPlot) {
        const rows = ('results' in response ? response.results : 'result' in response ? response.result : []) ?? []
        component = (
            <SqlBoxPlot
                rows={Array.isArray(rows) ? rows : []}
                columns={columns}
                chartSettings={chartSettings}
                analyticsKey={dataVisualizationProps.key}
                presetChartHeight={presetChartHeight}
            />
        )
    } else if (effectiveVisualizationType === ChartDisplayType.TwoDimensionalHeatmap) {
        component = (
            <TwoDimensionalHeatmap
                allowSorting={!(props.embedded && readOnly)}
                onInspect={canDrill ? inspect : undefined}
            />
        )
    } else if (effectiveVisualizationType === ChartDisplayType.BoldNumber) {
        component = <HogQLBoldNumber />
    } else if (effectiveVisualizationType === ChartDisplayType.Metric) {
        component = (
            <SqlMetricCard
                xData={xData}
                yData={yData}
                metricSettings={chartSettings.metric}
                presetChartHeight={presetChartHeight}
            />
        )
    }

    if (query.kind === NodeKind.BIVisualizationNode) {
        component = (
            <>
                {seriesBreakdownData.warning ? (
                    <LemonBanner type="info">{seriesBreakdownData.warning}</LemonBanner>
                ) : null}
                {!responseLoading && response && 'hasMore' in response && response.hasMore ? (
                    <LemonBanner type="info">
                        {query.config.compareFilter?.compare
                            ? `This worksheet reached its ${(query.config.limit / 2).toLocaleString()} comparison group limit. Space is reserved for both periods within the ${query.config.limit.toLocaleString()} row limit.`
                            : `This worksheet reached its ${query.config.limit.toLocaleString()} row limit.`}{' '}
                        Increase the limit or narrow the filters to see all results.
                    </LemonBanner>
                ) : null}
                {component}
                {canDrill ? (
                    <>
                        {resultMenu && (
                            <BIDrilldownMenu logicProps={drilldownProps} triggerRef={resultMenuTriggerRef} />
                        )}
                        <BIDrilldownModal
                            logicProps={drilldownProps}
                            navigationDisabledReason={props.context?.biHierarchyDrillDisabledReason}
                            onNavigate={
                                props.editMode && !props.inSharedMode ? props.context?.onDrillBIHierarchy : undefined
                            }
                        />
                    </>
                ) : null}
            </>
        )
    }

    if (props.embedded) {
        return (
            <div
                ref={resultMenuTriggerRef}
                className={clsx(
                    'DataVisualization InsightCard__viz',
                    effectiveVisualizationType === ChartDisplayType.Metric && 'InsightCard__viz--Metric'
                )}
                onClickCapture={
                    resultMenu
                        ? (event) => {
                              if (
                                  !replayingClick.current &&
                                  drilldownLogic.values.interaction &&
                                  event.currentTarget.contains(event.target as Node)
                              ) {
                                  closeResultMenu()
                              }
                          }
                        : undefined
                }
                onContextMenuCapture={
                    resultMenu
                        ? (event) => {
                              if (isResultMenuContextMenu(event)) {
                                  inspectedPoint.current = false
                              }
                          }
                        : undefined
                }
                onContextMenu={
                    resultMenu
                        ? (event) => {
                              if (!isResultMenuContextMenu(event)) {
                                  return
                              }
                              event.preventDefault()
                              setInteraction(getResultMenuPoint(event))
                              if (!inspectedPoint.current) {
                                  replayingClick.current = true
                                  try {
                                      replayAsClick(event)
                                  } finally {
                                      replayingClick.current = false
                                  }
                              }
                              if (!inspectedPoint.current) {
                                  inspect({})
                              }
                          }
                        : undefined
                }
            >
                {component}
            </div>
        )
    }

    return (
        <div
            className={clsx('DataVisualization flex min-h-0 min-w-0 flex-1 gap-2', {
                'h-full': effectiveVisualizationType !== ChartDisplayType.ActionsTable,
            })}
        >
            {!readOnly &&
                showResultControls &&
                settingsPanel?.isOpen &&
                settingsPanel.container &&
                createPortal(<SideBar className="w-full flex-1" />, settingsPanel.container)}
            <div className="relative min-h-0 min-w-0 w-full flex flex-col gap-2 flex-1 overflow-hidden">
                {!readOnly && showResultControls && (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="flex items-center gap-2 flex-wrap px-2">
                            <div className="flex gap-2 items-center">
                                <Reload size={controlSize} />
                                <ElapsedTime />
                            </div>
                            <AddVariableButton buttonProps={{ size: controlSize }} />

                            {sourceFeatures.has(QueryFeature.dateRangePicker) &&
                                query.kind !== NodeKind.BIVisualizationNode &&
                                !router.values.location.pathname.includes(urls.sqlEditor()) && ( // decouple this component from insights tab and datawarehouse scene
                                    <DateRange
                                        key="date-range"
                                        size={controlSize}
                                        query={query.source}
                                        setQuery={(query) => {
                                            if (query.kind === NodeKind.HogQLQuery) {
                                                setQuerySource(query)
                                            }
                                        }}
                                    />
                                )}

                            <div className={props.context?.chartTypeSelectorClassName}>
                                <TableDisplay
                                    size={controlSize}
                                    disabledReasonFor={(chartType) =>
                                        isQuerySnapshot && chartType === ChartDisplayType.TwoDimensionalHeatmap
                                            ? 'Query snapshots do not support pivots'
                                            : undefined
                                    }
                                />
                            </div>

                            <LemonButton
                                size={controlSize}
                                icon={<IconGear />}
                                type={(settingsPanel?.isOpen ?? isChartSettingsPanelOpen) ? 'primary' : 'secondary'}
                                onClick={settingsPanel?.onToggle ?? (() => toggleChartSettingsPanel())}
                                tooltip="Visualization settings"
                                aria-label="Visualization settings"
                            />

                            {query.kind === NodeKind.BIVisualizationNode &&
                                (effectiveVisualizationType === ChartDisplayType.ActionsTable ||
                                    isBIPivotTable(query.config)) && (
                                    <LemonButton
                                        size={controlSize}
                                        type="secondary"
                                        data-attr="bi-conditional-formatting"
                                        onClick={() => {
                                            setSideBarTab(SideBarTab.ConditionalFormatting)
                                            if (settingsPanel) {
                                                if (!settingsPanel.isOpen) {
                                                    settingsPanel.onToggle()
                                                }
                                            } else {
                                                toggleChartSettingsPanel(true)
                                            }
                                        }}
                                    >
                                        Conditional formatting
                                    </LemonButton>
                                )}

                            {props.exportContext && (
                                <ExportButton
                                    size={controlSize}
                                    disabledReason={
                                        effectiveVisualizationType !== ChartDisplayType.ActionsTable &&
                                        'Only table results are exportable'
                                    }
                                    type="secondary"
                                    items={[
                                        {
                                            export_format: ExporterFormat.CSV,
                                            export_context: props.exportContext,
                                        },
                                        {
                                            export_format: ExporterFormat.XLSX,
                                            export_context: props.exportContext,
                                        },
                                    ]}
                                />
                            )}
                        </div>
                    </>
                )}

                {!props.embedded && <VariablesForInsight />}

                <div className="flex min-h-0 min-w-0 flex-1 flex-row gap-2">
                    {/* The gear above toggles this panel (Series/Display tabs) — same layout the
                        SQL editor's OutputPane builds around its own visualization fork. */}
                    {!readOnly && showResultControls && !settingsPanel && isChartSettingsPanelOpen && (
                        <>
                            <SideBar />
                            <LemonDivider vertical className="h-full" />
                        </>
                    )}
                    <div className="min-h-0 min-w-0 w-full h-full flex-1 overflow-auto pb-3">{component}</div>
                </div>
            </div>
        </div>
    )
}
