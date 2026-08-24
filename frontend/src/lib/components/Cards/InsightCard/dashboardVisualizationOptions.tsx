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
    persistDisplayOptions,
}: {
    query: Node | null
    insightData: Record<string, any>
    variablesOverride?: Record<string, HogQLVariable> | null
    persistDisplayOptions?: (node: Node) => void
}): LemonMenuItems {
    const show = shouldShowSqlVisualizationPicker(query, !!persistDisplayOptions)

    // Dashboard date and property filters reach a HogQL query only through a {filters} placeholder,
    // which substitutes into a WHERE clause, so they change rows and never the columns the axes name.
    // A variable can appear in the SELECT list, so an overridden one can.
    const hasVariableOverride = !!variablesOverride && Object.keys(variablesOverride).length > 0

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
                                disabledReason={
                                    hasVariableOverride
                                        ? 'Open the insight to change its chart type while a variable is overridden'
                                        : undefined
                                }
                                persistDisplayOptions={persistDisplayOptions}
                            />
                        ),
                    },
                ],
            },
        ]
    }, [show, query, columns, types, rowCount, hasVariableOverride, persistDisplayOptions])
}
