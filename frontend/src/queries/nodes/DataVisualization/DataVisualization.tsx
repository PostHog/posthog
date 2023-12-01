import { LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { AnyResponseType, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { ElapsedTime } from '../DataNode/ElapsedTime'
import { Reload } from '../DataNode/Reload'
import { DataTable } from '../DataTable/DataTable'
import { HogQLQueryEditor } from '../HogQLQuery/HogQLQueryEditor'
import { Chart } from './Components/Chart'
import { TableDisplay } from './Components/TableDisplay'
import { dataVisualizationLogic, DataVisualizationLogicProps } from './dataVisualizationLogic'

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

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key,
        query: props.query,
        setQuery: props.setQuery,
        cachedResults: props.cachedResults,
    }
    const builtDataVisualizationLogic = dataVisualizationLogic(dataVisualizationLogicProps)

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: props.query.source,
        key,
        cachedResults: props.cachedResults,
    }

    const { query, visualizationType, showEditingUI } = useValues(builtDataVisualizationLogic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery]
    )

    let component: JSX.Element | null = null
    if (visualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <DataTable
                uniqueKey={key}
                query={{ kind: NodeKind.DataTableNode, source: query.source }}
                context={{
                    showQueryEditor: false,
                    showOpenEditorButton: false,
                }}
            />
        )
    } else if (visualizationType === ChartDisplayType.ActionsLineGraph) {
        component = <Chart />
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <div className="DataVisualization">
                    <div className="relative w-full flex flex-col gap-4 flex-1 overflow-hidden">
                        {showEditingUI && <HogQLQueryEditor query={query.source} setQuery={setQuerySource} embedded />}
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
                        {component}
                    </div>
                </div>
            </BindLogic>
        </BindLogic>
    )
}
