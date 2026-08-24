import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Node } from '~/queries/schema/schema-general'
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
    persistDisplayOptions,
}: {
    query: Node | null
    insightData: Record<string, any>
    persistDisplayOptions?: (node: Node) => void
}): LemonMenuItems {
    const { editingDisabledReason } = useValues(insightLogic)

    const show = shouldShowSqlVisualizationPicker(query, !!persistDisplayOptions)

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
                                // The axes it saves come from the filtered result, so an override
                                // would write one viewer's view onto the shared insight.
                                disabledReason={editingDisabledReason}
                                persistDisplayOptions={persistDisplayOptions}
                            />
                        ),
                    },
                ],
            },
        ]
    }, [show, query, columns, types, rowCount, editingDisabledReason, persistDisplayOptions])
}
