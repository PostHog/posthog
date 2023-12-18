import { LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { useCallback, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

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
}

let uniqueNode = 0

export function DataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const [uniqueNodeKey] = useState(() => uniqueNode++)
    const [key] = useState(`DataVisualizationNode.${props.uniqueKey?.toString() ?? uniqueNodeKey}`)

    const { insightProps: insightLogicProps } = useValues(insightLogic)

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key,
        query: props.query,
        insightLogicProps,
        setQuery: props.setQuery,
        cachedResults: props.cachedResults,
    }
    const builtDataVisualizationLogic = dataVisualizationLogic(dataVisualizationLogicProps)

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: props.query.source,
        key,
        cachedResults: props.cachedResults,
    }

    const { query, visualizationType, showEditingUI, showResultControls, sourceFeatures, response, responseLoading } =
        useValues(builtDataVisualizationLogic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery]
    )

    let component: JSX.Element | null = null
    if (!response && responseLoading) {
        return (
            <div className="flex flex-col flex-1 justify-center items-center border rounded bg-bg-light">
                <Animation type={AnimationType.LaptopHog} />
            </div>
        )
    } else if (visualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <DataTable
                uniqueKey={key}
                query={{ kind: NodeKind.DataTableNode, source: query.source }}
                cachedResults={props.cachedResults}
                context={{
                    showQueryEditor: false,
                    showOpenEditorButton: false,
                }}
            />
        )
    } else if (
        visualizationType === ChartDisplayType.ActionsLineGraph ||
        visualizationType === ChartDisplayType.ActionsBar
    ) {
        component = <Chart />
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <div className="DataVisualization flex flex-1">
                        <div className="relative w-full flex flex-col gap-4 flex-1 overflow-hidden">
                            {showEditingUI && (
                                <>
                                    <HogQLQueryEditor query={query.source} setQuery={setQuerySource} embedded />
                                    {sourceFeatures.has(QueryFeature.dateRangePicker) && (
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
                                </>
                            )}
                            {showResultControls && (
                                <>
                                    <LemonDivider className="my-0" />
                                    <div className="flex gap-4 justify-between flex-wrap">
                                        <div className="flex gap-4 items-center">
                                            <Reload />
                                            <ElapsedTime />
                                        </div>
                                        <div className="flex gap-4 items-center">
                                            <TableDisplay />
                                        </div>
                                    </div>
                                </>
                            )}
                            {component}
                        </div>
                    </div>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
