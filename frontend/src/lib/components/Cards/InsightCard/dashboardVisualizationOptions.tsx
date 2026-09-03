import { useCallback, useMemo, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { isDisplayTabSupported } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { DataVisualizationNode, HogQLVariable, Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNodeWithHogQLQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { DashboardSqlChartType, DashboardSqlDisplayOptions } from './DashboardSqlDisplayOptions'

export interface DashboardSqlVisualizationPersistence {
    saving: 'chart-type' | 'display-options' | null
    version: number
    persistChartType: (display: ChartDisplayType) => void
    persistDisplayOptions: (query: DataVisualizationNode) => void
}

export function sqlQueryForVisualizationPicker(query: Node | null, canPersist: boolean): DataVisualizationNode | null {
    return canPersist && query && isDataVisualizationNodeWithHogQLQuery(query) ? query : null
}

export function useDashboardVisualizationOptions({
    query,
    insightData,
    variablesOverride,
    loading,
    persistence,
}: {
    query: Node | null
    insightData: Record<string, any>
    variablesOverride?: Record<string, HogQLVariable> | null
    loading?: boolean
    persistence?: DashboardSqlVisualizationPersistence
}): LemonMenuItems {
    const sqlQuery = sqlQueryForVisualizationPicker(query, !!persistence)
    const overriddenVariable = Object.keys(sqlQuery?.source.variables ?? {}).find((key) => variablesOverride?.[key])

    const pickerProps = {
        query: sqlQuery,
        cachedResults: insightData,
        variablesOverride,
        loading,
        saving: persistence?.saving === 'chart-type',
        version: persistence?.version,
        overriddenVariable,
        persistChartType: persistence?.persistChartType,
    }
    const pickerPropsRef = useRef(pickerProps)
    pickerPropsRef.current = pickerProps
    const renderPicker = useCallback((): JSX.Element => {
        const props = pickerPropsRef.current
        return (
            <DashboardSqlChartType
                key={props.version}
                query={props.query!}
                cachedResults={props.cachedResults}
                variablesOverride={props.variablesOverride}
                loading={props.loading}
                saving={props.saving}
                disabledReason={
                    props.overriddenVariable
                        ? 'This dashboard overrides a variable this insight uses. Open the insight to change its chart type.'
                        : undefined
                }
                persistChartType={props.persistChartType!}
            />
        )
    }, [])

    const displayOptionsProps = {
        query: sqlQuery,
        cachedResults: insightData,
        variablesOverride,
        loading,
        persistence,
    }
    const displayOptionsPropsRef = useRef(displayOptionsProps)
    displayOptionsPropsRef.current = displayOptionsProps
    const renderDisplayOptions = useCallback((): JSX.Element => {
        const props = displayOptionsPropsRef.current
        if (props.loading) {
            return (
                <div className="flex min-h-20 w-80 items-center justify-center gap-2 text-muted" role="status">
                    <Spinner /> Loading display options
                </div>
            )
        }
        return (
            <DashboardSqlDisplayOptions
                key={props.persistence!.version}
                query={props.query!}
                cachedResults={props.cachedResults}
                variablesOverride={props.variablesOverride}
                persistDisplayOptions={props.persistence!.persistDisplayOptions}
                disabled={props.persistence!.saving === 'chart-type'}
            />
        )
    }, [])

    return useMemo<LemonMenuItems>(() => {
        if (!sqlQuery || !persistence) {
            return []
        }

        return [
            {
                title: 'Chart type',
                items: [{ label: renderPicker }],
            },
            isDisplayTabSupported(sqlQuery.display ?? ChartDisplayType.ActionsTable)
                ? {
                      key: 'display',
                      title: (
                          <h5 className="mx-2 my-1 flex items-center justify-between gap-2">
                              Display
                              {persistence.saving ? (
                                  <span className="flex items-center gap-1 font-normal text-muted" role="status">
                                      <Spinner /> Saving
                                  </span>
                              ) : null}
                          </h5>
                      ),
                      items: [{ label: renderDisplayOptions }],
                  }
                : false,
        ]
    }, [sqlQuery, persistence, renderPicker, renderDisplayOptions])
}
