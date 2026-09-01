import { useCallback, useMemo, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { isDisplayTabSupported } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { DataVisualizationNode, HogQLVariable, Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { DashboardSqlDisplayOptions } from './DashboardSqlDisplayOptions'
import { SqlVisualizationPicker } from './SqlVisualizationPicker'

// SQL insights only. A trends chart type goes through the editor's own action, which rewrites more
// than the display: it drops a breakdown the picked type cannot draw, and a box plot drops the
// formulas too. That is fine in the editor, where you see it before saving, but a card saves with no
// undo onto an insight every dashboard shares. A SQL insight has no such side effects.
export function sqlQueryForVisualizationPicker(query: Node | null, canPersist: boolean): DataVisualizationNode | null {
    return canPersist && query && isDataVisualizationNode(query) ? query : null
}

export function useDashboardVisualizationOptions({
    query,
    insightData,
    variablesOverride,
    loading,
    saving,
    savingSqlDisplayOptions,
    persistVisualizationType,
    persistSqlDisplayOptions,
}: {
    query: Node | null
    insightData: Record<string, any>
    variablesOverride?: Record<string, HogQLVariable> | null
    /** So a tile that has not produced results yet is not reported as having none. */
    loading?: boolean
    saving?: boolean
    savingSqlDisplayOptions?: boolean
    /** Present only when the viewer can save; also the gate for showing the picker at all. */
    persistVisualizationType?: (display: ChartDisplayType) => void
    persistSqlDisplayOptions?: (query: DataVisualizationNode) => void
}): LemonMenuItems {
    const sqlQuery = sqlQueryForVisualizationPicker(query, !!persistVisualizationType)
    const savingVisualizationChanges = saving || savingSqlDisplayOptions

    // Dashboard date and property filters reach a HogQL query only through a {filters} placeholder,
    // which substitutes into a WHERE clause, so they change rows and never the columns the axes name.
    // A variable can appear in the SELECT list, so an overridden one can. The override map is
    // dashboard-wide, so only a variable this insight actually uses counts.
    const overriddenVariable = Object.keys(sqlQuery?.source.variables ?? {}).find((key) => variablesOverride?.[key])

    const columns = insightData?.columns
    const types = insightData?.types
    const rowCount = Array.isArray(insightData?.result) ? insightData.result.length : 0

    const pickerProps = {
        query: sqlQuery,
        columns,
        types,
        rowCount,
        loading,
        saving: savingVisualizationChanges,
        overriddenVariable,
        persistVisualizationType,
    }
    // LemonMenu treats a custom label function as its component type, so its identity must stay stable.
    const pickerPropsRef = useRef(pickerProps)
    pickerPropsRef.current = pickerProps
    const renderPicker = useCallback((): JSX.Element => {
        const props = pickerPropsRef.current
        return (
            <SqlVisualizationPicker
                query={props.query!}
                columns={props.columns}
                types={props.types}
                rowCount={props.rowCount}
                loading={props.loading}
                saving={props.saving}
                disabledReason={
                    props.overriddenVariable
                        ? 'This dashboard overrides a variable this insight uses. Open the insight to change its chart type.'
                        : undefined
                }
                persistVisualizationType={props.persistVisualizationType!}
            />
        )
    }, [])

    const displayOptionsProps = {
        query: sqlQuery,
        cachedResults: insightData,
        variablesOverride,
        persistDisplayOptions: persistSqlDisplayOptions,
        loading,
        disabled: saving,
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
                query={props.query!}
                cachedResults={props.cachedResults}
                variablesOverride={props.variablesOverride}
                persistDisplayOptions={props.persistDisplayOptions!}
                disabled={props.disabled}
            />
        )
    }, [])

    return useMemo<LemonMenuItems>(() => {
        if (!sqlQuery || !persistVisualizationType) {
            return []
        }
        return [
            {
                title: 'Chart type',
                items: [
                    {
                        label: renderPicker,
                    },
                ],
            },
            persistSqlDisplayOptions && isDisplayTabSupported(sqlQuery.display ?? ChartDisplayType.ActionsTable)
                ? {
                      key: 'display',
                      title: (
                          <h5 className="mx-2 my-1 flex items-center justify-between gap-2">
                              Display
                              {savingVisualizationChanges ? (
                                  <span className="flex items-center gap-1 font-normal text-muted" role="status">
                                      <Spinner /> Saving
                                  </span>
                              ) : null}
                          </h5>
                      ),
                      items: [
                          {
                              label: renderDisplayOptions,
                          },
                      ],
                  }
                : false,
        ]
    }, [
        sqlQuery,
        savingVisualizationChanges,
        persistVisualizationType,
        persistSqlDisplayOptions,
        renderPicker,
        renderDisplayOptions,
    ])
}
