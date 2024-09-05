import './Components/Chart.scss'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { useCallback, useState } from 'react'
import { DatabaseTableTreeWithItems } from 'scenes/data-warehouse/external/DataWarehouseTables'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'
import { urls } from 'scenes/urls'

import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataVisualizationNode, HogQLQuery, HogQLQueryResponse, NodeKind } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { DateRange } from '../DataNode/DateRange'
import { ElapsedTime } from '../DataNode/ElapsedTime'
import { Reload } from '../DataNode/Reload'
import { QueryFeature } from '../DataTable/queryFeatures'
import { HogQLQueryEditor } from '../HogQLQuery/HogQLQueryEditor'
import { LineGraph } from './Components/Charts/LineGraph'
import { SideBar } from './Components/SideBar'
import { Table } from './Components/Table'
import { TableDisplay } from './Components/TableDisplay'
import { dataVisualizationLogic, DataVisualizationLogicProps } from './dataVisualizationLogic'
import { displayLogic } from './displayLogic'

interface DataTableVisualizationProps {
    uniqueKey?: string | number
    query: DataVisualizationNode
    setQuery?: (query: DataVisualizationNode) => void
    context?: QueryContext<DataVisualizationNode>
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
    readOnly?: boolean
}

let uniqueNode = 0

export function DataTableVisualization({
    uniqueKey,
    query,
    setQuery,
    context,
    cachedResults,
    readOnly,
}: DataTableVisualizationProps): JSX.Element {
    const [key] = useState(`DataVisualizationNode.${uniqueKey ?? uniqueNode++}`)
    const insightProps: InsightLogicProps<DataVisualizationNode> = context?.insightProps || {
        dashboardItemId: `new-AdHoc.${key}`,
        query,
        setQuery,
        dataNodeCollectionId: key,
    }

    const vizKey = insightVizDataNodeKey(insightProps)
    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: vizKey,
        query,
        insightLogicProps: insightProps,
        setQuery,
        cachedResults,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        cachedResults,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId: insightVizDataCollectionId(insightProps, key),
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <InternalDataTableVisualization
                        uniqueKey={key}
                        query={query}
                        setQuery={setQuery}
                        context={context}
                        cachedResults={cachedResults}
                        readOnly={readOnly}
                    />
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
        showEditingUI,
        showResultControls,
        sourceFeatures,
        response,
        responseLoading,
        responseError,
        queryCancelled,
        isChartSettingsPanelOpen,
    } = useValues(dataVisualizationLogic)

    const { toggleChartSettingsPanel } = useActions(dataVisualizationLogic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery]
    )

    if (!showEditingUI && (!response || responseLoading)) {
        return (
            <div className="flex flex-col flex-1 justify-center items-center border rounded bg-bg-light">
                <Animation type={AnimationType.LaptopHog} />
            </div>
        )
    }
    let component: JSX.Element | null = null
    if (visualizationType === ChartDisplayType.ActionsTable) {
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
        component = <LineGraph />
    } else if (visualizationType === ChartDisplayType.BoldNumber) {
        component = <HogQLBoldNumber />
    }

    return (
        <div className="DataVisualization flex flex-1 gap-2">
            {!readOnly && showEditingUI && (
                <div className="max-sm:hidden max-w-xs">
                    <DatabaseTableTreeWithItems inline />
                </div>
            )}
            <div className="relative w-full flex flex-col gap-4 flex-1 overflow-hidden">
                {!readOnly && showEditingUI && (
                    <>
                        <HogQLQueryEditor query={query.source} setQuery={setQuerySource} embedded />
                    </>
                )}
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
                                    {sourceFeatures.has(QueryFeature.dateRangePicker) &&
                                        !router.values.location.pathname.includes(urls.dataWarehouse()) && ( // decouple this component from insights tab and datawarehouse scene
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
                                </div>
                            </div>
                        </div>
                    </>
                )}
                <div className="flex flex-1 flex-row gap-4">
                    {showEditingUI && isChartSettingsPanelOpen && (
                        <div className="h-full">
                            <SideBar />
                        </div>
                    )}
                    <div
                        className={clsx('w-full h-full flex-1 overflow-auto', {
                            'pt-[46px]': showEditingUI,
                        })}
                    >
                        {visualizationType !== ChartDisplayType.ActionsTable && responseError ? (
                            <div
                                className={clsx('rounded bg-bg-light relative flex flex-1 flex-col p-2', {
                                    border: showEditingUI,
                                })}
                            >
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
