import { useMemo } from 'react'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { ChartSettings, DataVisualizationNode, HogQLVariable, Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { SqlVisualizationPicker } from './SqlVisualizationPicker'

// SQL insights only. A trends chart type goes through the editor's own action, which rewrites more
// than the display: it drops a breakdown the picked type cannot draw, and a box plot drops the
// formulas too. That is fine in the editor, where you see it before saving, but a card saves with no
// undo onto an insight every dashboard shares. A SQL insight has no such side effects.
export function sqlQueryForVisualizationPicker(query: Node | null, canPersist: boolean): DataVisualizationNode | null {
    return canPersist && query && isDataVisualizationNode(query) ? query : null
}

// The chart type section of a dashboard card's "Display options" menu, so switching how a SQL insight
// is drawn no longer means a round trip through the insight editor.
export function useDashboardVisualizationOptions({
    query,
    insightData,
    variablesOverride,
    loading,
    saving,
    persistVisualizationType,
}: {
    query: Node | null
    insightData: Record<string, any>
    variablesOverride?: Record<string, HogQLVariable> | null
    /** So a tile that has not produced results yet is not reported as having none. */
    loading?: boolean
    saving?: boolean
    /** Present only when the viewer can save; also the gate for showing the picker at all. */
    persistVisualizationType?: (display: ChartDisplayType, chartSettings: ChartSettings) => void
}): LemonMenuItems {
    const sqlQuery = sqlQueryForVisualizationPicker(query, !!persistVisualizationType)

    // Dashboard date and property filters reach a HogQL query only through a {filters} placeholder,
    // which substitutes into a WHERE clause, so they change rows and never the columns the axes name.
    // A variable can appear in the SELECT list, so an overridden one can. The override map is
    // dashboard-wide, so only a variable this insight actually uses counts.
    const overriddenVariable = Object.keys(sqlQuery?.source.variables ?? {}).find((key) => variablesOverride?.[key])

    // Keyed on the response arrays rather than insightData itself: that object is rebuilt on every
    // refresh tick, and a new label identity would remount the picker and close its open dropdown.
    const columns = insightData?.columns
    const types = insightData?.types
    const rowCount = Array.isArray(insightData?.result) ? insightData.result.length : 0

    return useMemo<LemonMenuItems>(() => {
        if (!sqlQuery || !persistVisualizationType) {
            return []
        }
        return [
            {
                title: 'Chart type',
                items: [
                    {
                        label: () => (
                            <SqlVisualizationPicker
                                query={sqlQuery}
                                columns={columns}
                                types={types}
                                rowCount={rowCount}
                                loading={loading}
                                saving={saving}
                                disabledReason={
                                    overriddenVariable
                                        ? 'This dashboard overrides a variable this insight uses. Open the insight to change its chart type.'
                                        : undefined
                                }
                                persistVisualizationType={persistVisualizationType}
                            />
                        ),
                    },
                ],
            },
        ]
    }, [sqlQuery, columns, types, rowCount, loading, saving, overriddenVariable, persistVisualizationType])
}
