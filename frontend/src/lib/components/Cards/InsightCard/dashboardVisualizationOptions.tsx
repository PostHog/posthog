import { useValues } from 'kea'
import { useMemo } from 'react'

import { ChartFilter } from 'lib/components/ChartFilter'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'

import { SqlVisualizationPicker } from './SqlVisualizationPicker'

// LemonMenu renders a function label as a component type, so a fresh closure on each render remounts
// the picker and closes its dropdown mid-interaction. This one is defined once.
const TRENDS_SECTION: LemonMenuItems = [
    {
        title: 'Chart type',
        items: [
            {
                label: () => (
                    <ChartFilter
                        fullWidth
                        allowEditingWithOverrides
                        className="pb-2 px-2"
                        dataAttr="dashboard-insight-visualization-picker"
                    />
                ),
            },
        ],
    },
]

// Only insight types whose chart type is a single dropdown get a picker. Funnels, retention and paths
// each pick a chart through their own bespoke control, so they get nothing here. `supportsDisplay` is
// the same gate the insight editor uses to show its chart type dropdown.
export function resolveVisualizationPicker(
    query: Node | null,
    supportsDisplay: boolean,
    canPersist: boolean
): 'sql' | 'trends' | null {
    if (!canPersist || !query) {
        return null
    }
    if (isDataVisualizationNode(query)) {
        return 'sql'
    }
    return supportsDisplay ? 'trends' : null
}

// The chart type section of a dashboard card's "Display options" menu, so switching how an insight is
// drawn no longer means a round trip through the insight editor.
export function useDashboardVisualizationOptions({
    query,
    insightData,
    persistDisplayOptions,
}: {
    query: Node | null
    insightData: Record<string, any>
    persistDisplayOptions?: (node: Node) => void
}): LemonMenuItems {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { supportsDisplay } = useValues(insightVizDataLogic(insightProps))

    const kind = resolveVisualizationPicker(query, supportsDisplay, !!persistDisplayOptions)

    // Keyed on the response arrays rather than insightData itself: that object is rebuilt on every
    // refresh tick, and a new label identity would remount the picker and close its open dropdown.
    const columns = insightData?.columns
    const types = insightData?.types
    const rowCount = Array.isArray(insightData?.result) ? insightData.result.length : 0

    const sqlSection = useMemo<LemonMenuItems>(() => {
        if (kind !== 'sql' || !persistDisplayOptions || !query || !isDataVisualizationNode(query)) {
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
    }, [kind, query, columns, types, rowCount, editingDisabledReason, persistDisplayOptions])

    if (kind === 'sql') {
        return sqlSection
    }
    return kind === 'trends' ? TRENDS_SECTION : []
}
