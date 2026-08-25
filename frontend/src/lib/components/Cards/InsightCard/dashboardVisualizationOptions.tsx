import { useMemo } from 'react'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { HogQLVariable, Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'

import { SqlVisualizationPicker } from './SqlVisualizationPicker'

// SQL insights only. A trends chart type goes through the editor's own action, which rewrites more
// than the display: it drops a breakdown the picked type cannot draw, and a box plot drops the
// formulas too. That is fine in the editor, where you see it before saving, but a card saves with no
// undo onto an insight every dashboard shares. A SQL insight has no such side effects.
export function shouldShowSqlVisualizationPicker(query: Node | null, canPersist: boolean): boolean {
    return canPersist && !!query && isDataVisualizationNode(query)
}

// The chart type section of a dashboard card's "Display options" menu, so switching how a SQL insight
// is drawn no longer means a round trip through the insight editor.
export function useDashboardVisualizationOptions({
    query,
    insightData,
    variablesOverride,
    loading,
    saving,
    persistDisplayOptions,
}: {
    query: Node | null
    insightData: Record<string, any>
    variablesOverride?: Record<string, HogQLVariable> | null
    /** So a tile that has not produced results yet is not reported as having none. */
    loading?: boolean
    saving?: boolean
    persistDisplayOptions?: (node: Node) => void
}): LemonMenuItems {
    const show = shouldShowSqlVisualizationPicker(query, !!persistDisplayOptions)

    // Dashboard date and property filters reach a HogQL query only through a {filters} placeholder,
    // which substitutes into a WHERE clause, so they change rows and never the columns the axes name.
    // A variable can appear in the SELECT list, so an overridden one can. The override map is
    // dashboard-wide, so only a variable this insight actually uses counts.
    const insightVariables = query && isDataVisualizationNode(query) ? query.source.variables : undefined
    const overriddenVariable = Object.keys(insightVariables ?? {}).find((key) => variablesOverride?.[key])

    // Keyed on the response arrays rather than insightData itself: that object is rebuilt on every
    // refresh tick, and a new label identity would remount the picker and close its open dropdown.
    const columns = insightData?.columns
    const types = insightData?.types
    const rowCount = Array.isArray(insightData?.result) ? insightData.result.length : 0

    return useMemo<LemonMenuItems>(() => {
        if (!show || !persistDisplayOptions || !query || !isDataVisualizationNode(query)) {
            return []
        }
        return [
            {
                title: 'Chart type',
                items: [
                    {
                        label: () => (
                            <SqlVisualizationPicker
                                query={query}
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
                                persistDisplayOptions={persistDisplayOptions}
                            />
                        ),
                    },
                ],
            },
        ]
    }, [show, query, columns, types, rowCount, loading, saving, overriddenVariable, persistDisplayOptions])
}
