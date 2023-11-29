import { BindLogic, useValues } from 'kea'
import { uuid } from 'lib/utils'
import { useCallback, useState } from 'react'

import { AnyResponseType, DataVisualizationNode, HogQLQuery } from '~/queries/schema'

import { HogQLQueryEditor } from '../HogQLQuery/HogQLQueryEditor'
import { ChartSelection } from './Components/ChartSelection'
import { dataVisualizationLogic } from './dataVisualizationLogic'

interface DataTableVisualizationProps {
    uniqueKey?: string | number
    query: DataVisualizationNode
    setQuery?: (query: DataVisualizationNode) => void
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

export function DataTableVisualization(props: DataTableVisualizationProps): JSX.Element {
    const [key] = useState(props.uniqueKey?.toString() ?? uuid())

    const logicProps = {
        key,
        query: props.query,
        cachedResults: props.cachedResults,
    }
    const logic = dataVisualizationLogic(logicProps)

    const { query } = useValues(logic)

    const setQuerySource = useCallback(
        (source: HogQLQuery) => props.setQuery?.({ ...props.query, source }),
        [props.setQuery]
    )

    return (
        <BindLogic logic={dataVisualizationLogic} props={logicProps}>
            <div className="DataVisualization">
                <HogQLQueryEditor query={query.source} setQuery={setQuerySource} embedded />
                <ChartSelection />
            </div>
        </BindLogic>
    )
}
