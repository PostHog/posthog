import { LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { uuid } from 'lib/utils'
import { useCallback, useState } from 'react'

import { AnyResponseType, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { DataTable } from '../DataTable/DataTable'
import { HogQLQueryEditor } from '../HogQLQuery/HogQLQueryEditor'
import { Chart } from './Components/Chart'
import { ElapsedTime } from './Components/ElapsedTime'
import { Reload } from './Components/Reload'
import { TableDisplay } from './Components/TableDisplay'
import { dataVisualizationLogic } from './dataVisualizationLogic'

interface DataTableVisualizationProps {
    uniqueKey?: string | number
    query: DataVisualizationNode
    setQuery?: (query: DataVisualizationNode) => void
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

export function DataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const [key] = useState(props.uniqueKey?.toString() ?? uuid())

    const logicProps = {
        key,
        query: props.query,
        setQuery: props.setQuery,
        cachedResults: props.cachedResults,
    }
    const logic = dataVisualizationLogic(logicProps)

    const { query, visualizationType, showEditingUI } = useValues(logic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery]
    )

    let component: JSX.Element | null = null
    if (visualizationType === ChartDisplayType.ActionsTable) {
        component = (
            <DataTable
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
        <BindLogic logic={dataVisualizationLogic} props={logicProps}>
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
    )
}
