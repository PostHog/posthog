import { LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { useCallback, useState } from 'react'
import { DatabaseTableTreeWithItems } from 'scenes/data-warehouse/external/DataWarehouseTables'
import { insightLogic } from 'scenes/insights/insightLogic'
import { HogQLBoldNumber } from 'scenes/insights/views/BoldNumber/BoldNumber'
import { urls } from 'scenes/urls'

import { insightVizDataCollectionId, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { DateRange } from '../DataNode/DateRange'
import { ElapsedTime } from '../DataNode/ElapsedTime'
import { Reload } from '../DataNode/Reload'
import { DataTable } from '../DataTable/DataTable'
import { QueryFeature } from '../DataTable/queryFeatures'
import { HogQLQueryEditor } from '../HogQLQuery/HogQLQueryEditor'
import { Chart } from './Components/Chart'
import { TableDisplay } from './Components/TableDisplay'
import { dataVisualizationLogic, DataVisualizationLogicProps } from './dataVisualizationLogic'
import { displayLogic } from './displayLogic'

interface DataTableVisualizationProps {
    uniqueKey?: string | number
    query: DataVisualizationNode
    setQuery?: (query: DataVisualizationNode) => void
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
    readOnly?: boolean
}

let uniqueNode = 0

export function DataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const [uniqueNodeKey] = useState(() => uniqueNode++)
    const [key] = useState(`DataVisualizationNode.${props.uniqueKey?.toString() ?? uniqueNodeKey}`)

    const { insightProps: insightLogicProps } = useValues(insightLogic)

    const vizKey = insightVizDataNodeKey(insightLogicProps)
    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: vizKey,
        query: props.query,
        insightLogicProps,
        setQuery: props.setQuery,
        cachedResults: props.cachedResults,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: props.query.source,
        key: vizKey,
        cachedResults: props.cachedResults,
        loadPriority: insightLogicProps.loadPriority,
        dataNodeCollectionId: insightVizDataCollectionId(insightLogicProps, key),
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <InternalDataTableVisualization {...props} uniqueKey={key} />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function InternalDataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const { readOnly } = props
    const { query, visualizationType, showEditingUI, showResultControls, sourceFeatures, response, responseLoading } =
        useValues(dataVisualizationLogic)

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
            <DataTable
                uniqueKey={props.uniqueKey}
                dataNodeLogicKey={props.uniqueKey?.toString()}
                query={{ kind: NodeKind.DataTableNode, source: query.source }}
                cachedResults={props.cachedResults}
                context={{
                    ...props.context,
                    showQueryEditor: false,
                    showOpenEditorButton: false,
                }}
            />
        )
    } else if (
        visualizationType === ChartDisplayType.ActionsLineGraph ||
        visualizationType === ChartDisplayType.ActionsBar ||
        visualizationType === ChartDisplayType.ActionsAreaGraph ||
        visualizationType === ChartDisplayType.ActionsStackedBar
    ) {
        component = <Chart />
    } else if (visualizationType === ChartDisplayType.BoldNumber) {
        component = <HogQLBoldNumber />
    }

    return (
        <div className="DataVisualization flex flex-1 gap-2">
            {!readOnly && showEditingUI && (
                <div className="flex max-sm:hidden">
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
                        <div className="flex gap-4 justify-between flex-wrap">
                            <div className="flex gap-4 items-center">
                                <Reload />
                                <ElapsedTime />
                            </div>
                            <div className="flex gap-4 items-center">
                                {sourceFeatures.has(QueryFeature.dateRangePicker) &&
                                    !router.values.location.pathname.includes(urls.dataWarehouse()) && ( // decouple this component from insights tab and datawarehouse scene
                                        <div className="flex gap-4 items-center flex-wrap">
                                            <DateRange
                                                key="date-range"
                                                query={query.source}
                                                setQuery={(query) => {
                                                    if (query.kind === NodeKind.HogQLQuery) {
                                                        setQuerySource(query)
                                                    }
                                                }}
                                            />
                                        </div>
                                    )}
                                <TableDisplay />
                            </div>
                        </div>
                    </>
                )}
                {component}
            </div>
        </div>
    )
}
