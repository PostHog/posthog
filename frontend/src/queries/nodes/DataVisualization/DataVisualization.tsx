import clsx from 'clsx'
import { BindLogic, BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightErrorState, StatelessInsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'
import { urls } from 'scenes/urls'

import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import {
    AnyResponseType,
    DataVisualizationNode,
    HogQLQuery,
    HogQLQueryResponse,
    HogQLVariable,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { shouldQueryBeAsync } from '~/queries/utils'
import { ChartDisplayType, ExportContext, ExporterFormat, InsightLogicProps } from '~/types'

import { DateRange } from '../DataNode/DateRange'
import { ElapsedTime } from '../DataNode/ElapsedTime'
import { Reload } from '../DataNode/Reload'
import { DataNodeLogicProps, dataNodeLogic } from '../DataNode/dataNodeLogic'
import { QueryFeature } from '../DataTable/queryFeatures'
import { LineGraph } from './Components/Charts/LineGraph'
import { Table } from './Components/Table'
import { TableDisplay } from './Components/TableDisplay'
import { AddVariableButton } from './Components/Variables/AddVariableButton'
import { VariablesForInsight } from './Components/Variables/Variables'
import { variableModalLogic } from './Components/Variables/variableModalLogic'
import { VariablesLogicProps, variablesLogic } from './Components/Variables/variablesLogic'
import { seriesBreakdownLogic } from './Components/seriesBreakdownLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from './dataVisualizationLogic'
import { displayLogic } from './displayLogic'

export interface DataTableVisualizationProps {
    uniqueKey?: string | number
    query: DataVisualizationNode
    setQuery: (query: DataVisualizationNode) => void
    context?: QueryContext<DataVisualizationNode>
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
    editMode?: boolean
    readOnly?: boolean
    exportContext?: ExportContext
    /** Dashboard variables to override the ones in the query */
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
    attachTo,
    editMode,
}: DataTableVisualizationProps): JSX.Element {
    const [key] = useState(`DataVisualizationNode.${uniqueKey ?? uniqueNode++}`)
    const insightProps: InsightLogicProps<DataVisualizationNode> = context?.insightProps || {
        dashboardItemId: `new-AdHoc.${key}`,
        query,
        setQuery,
        dataNodeCollectionId: key,
    }

    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeCollectionId = insightVizDataCollectionId(insightProps, key)
    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: vizKey,
        query,
        dashboardId: insightProps.dashboardId,
        dataNodeCollectionId,
        loadPriority: insightProps.loadPriority,
        editMode,
        setQuery: (setter) => {
            setQuery(setter(query))
        },
        cachedResults,
        variablesOverride,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        cachedResults,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId,
        variablesOverride,
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
        onUpdate: (query: DataVisualizationNode) => {
            loadData(shouldQueryBeAsync(query.source) ? 'force_async' : 'force_blocking', undefined, query.source)
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

    const {
        query,
        visualizationType,
        showResultControls,
        sourceFeatures,
        response,
        responseLoading,
        responseError,
        queryCancelled,
        isChartSettingsPanelOpen,
        xData,
        yData,
        chartSettings,
        dashboardId,
        dataVisualizationProps,
        presetChartHeight,
    } = useValues(dataVisualizationLogic)

    const { seriesBreakdownData } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { goalLines } = useValues(displayLogic)

    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)

    const { queryId, pollResponse } = useValues(dataNodeLogic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery, props.query] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    let component: JSX.Element | null = null

    // TODO(@Gilbert09): Better loading support for all components - e.g. using the `loading` param of `Table`
    if (!response || responseLoading) {
        component = (
            <div className="flex flex-col flex-1 justify-center items-center bg-surface-primary h-full">
                <StatelessInsightLoadingState queryId={queryId} pollResponse={pollResponse} />
            </div>
        )
    } else if (visualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <Table
                uniqueKey={props.uniqueKey}
                query={query}
                context={props.context}
                cachedResults={props.cachedResults as HogQLQueryResponse | undefined}
            />
        )
    } else if (
        visualizationType === ChartDisplayType.ActionsLineGraph ||
        visualizationType === ChartDisplayType.ActionsBar ||
        visualizationType === ChartDisplayType.ActionsAreaGraph ||
        visualizationType === ChartDisplayType.ActionsStackedBar
    ) {
        const _xData = seriesBreakdownData.xData.data.length ? seriesBreakdownData.xData : xData
        const _yData = seriesBreakdownData.xData.data.length ? seriesBreakdownData.seriesData : yData
        component = (
            <LineGraph
                className="p-2"
                xData={_xData}
                yData={_yData}
                visualizationType={visualizationType}
                chartSettings={chartSettings}
                dashboardId={dashboardId}
                goalLines={goalLines}
                presetChartHeight={presetChartHeight}
            />
        )
    } else if (visualizationType === ChartDisplayType.BoldNumber) {
        component = <HogQLBoldNumber />
    }

    return (
        <div
            className={clsx('DataVisualization flex flex-1 gap-2', {
                'h-full': visualizationType !== ChartDisplayType.ActionsTable,
            })}
        >
            <div className="relative w-full flex flex-col gap-4 flex-1 overflow-hidden">
                {!readOnly && showResultControls && (
                    <>
                        <LemonDivider className="my-0" />
                        <div className="flex gap-4 justify-between flex-wrap px-px">
                            <div className="flex gap-4 items-center">
                                <Reload />
                                <ElapsedTime />
                            </div>
                            <div className="flex gap-4 items-center">
                                <div className="flex gap-4 items-center flex-wrap">
                                    <AddVariableButton />

                                    {sourceFeatures.has(QueryFeature.dateRangePicker) &&
                                        !router.values.location.pathname.includes(urls.sqlEditor()) && ( // decouple this component from insights tab and datawarehouse scene
                                            <DateRange
                                                key="date-range"
                                                query={query.source}
                                                setQuery={(query) => {
                                                    if (query.kind === NodeKind.HogQLQuery) {
                                                        setQuerySource(query)
                                                    }
                                                }}
                                            />
                                        )}

                                    <TableDisplay />

                                    <LemonButton
                                        icon={<IconGear />}
                                        type={isChartSettingsPanelOpen ? 'primary' : 'secondary'}
                                        onClick={() => toggleChartSettingsPanel()}
                                        tooltip="Visualization settings"
                                    />

                                    {props.exportContext && (
                                        <ExportButton
                                            disabledReason={
                                                visualizationType != ChartDisplayType.ActionsTable &&
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
                            </div>
                        </div>
                    </>
                )}

                <VariablesForInsight />

                <div className="flex flex-1 flex-row gap-4">
                    <div className={clsx('w-full h-full flex-1 overflow-auto')}>
                        {visualizationType !== ChartDisplayType.ActionsTable && responseError ? (
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
                        ) : (
                            component
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
