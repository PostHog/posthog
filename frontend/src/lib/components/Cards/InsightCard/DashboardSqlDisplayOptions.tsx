import './DashboardSqlDisplayOptions.scss'

import { BindLogic } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { DisplayTab } from '~/queries/nodes/DataVisualization/Components/DisplayTab'
import {
    DataVisualizationLogicProps,
    dataVisualizationLogic,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { applyDataVisualizationQueryUpdate } from '~/queries/nodes/DataVisualization/queryUpdateUtils'
import { AnyResponseType, DataVisualizationNode, HogQLVariable } from '~/queries/schema/schema-general'

let uniqueNode = 0

export function DashboardSqlDisplayOptions({
    query,
    cachedResults,
    variablesOverride,
    persistDisplayOptions,
    disabled,
}: {
    query: DataVisualizationNode
    cachedResults: AnyResponseType
    variablesOverride?: Record<string, HogQLVariable> | null
    persistDisplayOptions: (query: DataVisualizationNode) => void
    disabled?: boolean
}): JSX.Element {
    const [key] = useState(`dashboard-sql-display-options.${uniqueNode++}`)
    const queryRef = useRef(query)
    const queryPropRef = useRef(query)
    const hasMountedRef = useRef(false)
    if (queryPropRef.current !== query) {
        queryPropRef.current = query
        queryRef.current = query
    }
    useEffect(() => {
        hasMountedRef.current = true
    }, [])
    const setQuery = useCallback(
        (setter: Parameters<typeof applyDataVisualizationQueryUpdate>[1]) =>
            applyDataVisualizationQueryUpdate(queryRef, setter, (nextQuery) => {
                if (hasMountedRef.current) {
                    persistDisplayOptions(nextQuery)
                }
            }),
        [persistDisplayOptions]
    )

    const logicProps: DataVisualizationLogicProps = {
        key,
        query: queryRef.current,
        dataNodeCollectionId: key,
        cachedResults,
        variablesOverride,
        setQuery,
    }
    const inertProps = disabled ? { inert: '' } : {}

    return (
        <div
            {...inertProps}
            className={`DashboardSqlDisplayOptions w-80 max-h-96 overflow-y-auto ${
                disabled ? 'pointer-events-none opacity-50' : ''
            }`}
            aria-disabled={disabled}
        >
            <BindLogic logic={dataVisualizationLogic} props={logicProps}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        </div>
    )
}
