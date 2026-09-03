import './DashboardSqlDisplayOptions.scss'

import { BindLogic, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { DisplayTab } from '~/queries/nodes/DataVisualization/Components/DisplayTab'
import { TableDisplay } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import {
    DataVisualizationLogicProps,
    dataVisualizationLogic,
    rowCountFromResponse,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { applyDataVisualizationQueryUpdate } from '~/queries/nodes/DataVisualization/queryUpdateUtils'
import { sqlVisualizationDisabledReason } from '~/queries/nodes/DataVisualization/sqlVisualizationSupport'
import { AnyResponseType, DataVisualizationNode, HogQLVariable } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

let uniqueNode = 0

interface DashboardSqlVisualizationLogicProps {
    query: DataVisualizationNode
    cachedResults: AnyResponseType
    variablesOverride?: Record<string, HogQLVariable> | null
    persistQuery: (query: DataVisualizationNode) => void
    children: ReactNode
}

function DashboardSqlVisualizationLogic({
    query,
    cachedResults,
    variablesOverride,
    persistQuery,
    children,
}: DashboardSqlVisualizationLogicProps): JSX.Element {
    const [key] = useState(`dashboard-sql-visualization.${uniqueNode++}`)
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
                    persistQuery(nextQuery)
                }
            }),
        [persistQuery]
    )

    const logicProps: DataVisualizationLogicProps = {
        key,
        query: queryRef.current,
        dataNodeCollectionId: key,
        cachedResults,
        variablesOverride,
        setQuery,
    }

    return (
        <BindLogic logic={dataVisualizationLogic} props={logicProps}>
            <BindLogic logic={displayLogic} props={{ key }}>
                {children}
            </BindLogic>
        </BindLogic>
    )
}

function DashboardSqlChartTypeControl({
    disabledReason,
    loading,
    saving,
}: {
    disabledReason?: string
    loading?: boolean
    saving?: boolean
}): JSX.Element {
    const { autoVisualizationType, columns, query, response } = useValues(dataVisualizationLogic)
    const rowCount = rowCountFromResponse(response)
    const disabledReasonFor = useCallback(
        (display: ChartDisplayType): string | undefined =>
            sqlVisualizationDisabledReason(display, query, columns, rowCount, autoVisualizationType),
        [query, columns, rowCount, autoVisualizationType]
    )
    let chartTypeDisabledReason = disabledReason
    if (chartTypeDisabledReason === undefined) {
        if (saving) {
            chartTypeDisabledReason = 'Saving chart type'
        } else if (loading) {
            chartTypeDisabledReason = 'Waiting for this insight to load'
        } else if (columns.length === 0) {
            chartTypeDisabledReason = 'This insight returned no columns to visualize'
        }
    }

    return (
        <div className="pb-2 px-2">
            <TableDisplay
                dataAttr="dashboard-insight-visualization-picker"
                disabledReason={chartTypeDisabledReason}
                disabledReasonFor={disabledReasonFor}
                fullWidth
                loading={saving}
            />
        </div>
    )
}

interface DashboardSqlVisualizationProps {
    query: DataVisualizationNode
    cachedResults: AnyResponseType
    variablesOverride?: Record<string, HogQLVariable> | null
}

export function DashboardSqlChartType({
    query,
    cachedResults,
    variablesOverride,
    persistChartType,
    disabledReason,
    loading,
    saving,
}: DashboardSqlVisualizationProps & {
    persistChartType: (display: ChartDisplayType) => void
    disabledReason?: string
    loading?: boolean
    saving?: boolean
}): JSX.Element {
    const persistQuery = useCallback(
        (nextQuery: DataVisualizationNode): void =>
            persistChartType(nextQuery.display ?? ChartDisplayType.ActionsTable),
        [persistChartType]
    )

    return (
        <DashboardSqlVisualizationLogic
            query={query}
            cachedResults={cachedResults}
            variablesOverride={variablesOverride}
            persistQuery={persistQuery}
        >
            <DashboardSqlChartTypeControl disabledReason={disabledReason} loading={loading} saving={saving} />
        </DashboardSqlVisualizationLogic>
    )
}

export function DashboardSqlDisplayOptions({
    query,
    cachedResults,
    variablesOverride,
    persistDisplayOptions,
    disabled,
}: DashboardSqlVisualizationProps & {
    persistDisplayOptions: (query: DataVisualizationNode) => void
    disabled?: boolean
}): JSX.Element {
    const inertProps = disabled ? { inert: '' } : {}

    return (
        <DashboardSqlVisualizationLogic
            query={query}
            cachedResults={cachedResults}
            variablesOverride={variablesOverride}
            persistQuery={persistDisplayOptions}
        >
            <div
                {...inertProps}
                className={`DashboardSqlDisplayOptions w-80 max-h-96 overflow-y-auto ${
                    disabled ? 'pointer-events-none opacity-50' : ''
                }`}
                aria-disabled={disabled}
            >
                <DisplayTab />
            </div>
        </DashboardSqlVisualizationLogic>
    )
}
