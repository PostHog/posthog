import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DataVisualizationNode, Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'

import { SqlVisualizationPicker } from './SqlVisualizationPicker'
import { TrendsVisualizationPicker } from './TrendsVisualizationPicker'

export type VisualizationPicker =
    | { kind: 'sql'; query: DataVisualizationNode; persistDisplayOptions: (node: Node) => void }
    | { kind: 'trends' }
    | null

// LemonMenu renders a function label as a component type, so a fresh closure on each render remounts
// the picker and closes its dropdown mid-interaction. This one is defined once.
const TRENDS_SECTION: LemonMenuItems = [
    { title: 'Visualization', items: [{ label: () => <TrendsVisualizationPicker /> }] },
]

// Only insight types whose chart type is a single dropdown get a picker. Funnels, retention and paths
// each pick a chart through their own bespoke control, so they get nothing here.
export function resolveVisualizationPicker(
    query: Node | null,
    supportsDisplay: boolean,
    persistDisplayOptions?: (node: Node) => void
): VisualizationPicker {
    if (!persistDisplayOptions || !query) {
        return null
    }

    if (isDataVisualizationNode(query)) {
        return { kind: 'sql', query, persistDisplayOptions }
    }

    return supportsDisplay ? { kind: 'trends' } : null
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
    const { insightProps } = useValues(insightLogic)
    const { supportsDisplay } = useValues(insightVizDataLogic(insightProps))

    const picker = resolveVisualizationPicker(query, supportsDisplay, persistDisplayOptions)
    const sqlQuery = picker?.kind === 'sql' ? picker.query : null
    const sqlPersist = picker?.kind === 'sql' ? picker.persistDisplayOptions : undefined

    // Keyed on the response arrays rather than insightData itself: that object is rebuilt on every
    // refresh tick, and a new label identity would remount the picker and close its open dropdown.
    const columns = insightData?.columns
    const types = insightData?.types
    const result = insightData?.result

    const sqlSection = useMemo<LemonMenuItems>(() => {
        if (!sqlQuery || !sqlPersist) {
            return []
        }
        return [
            {
                title: 'Visualization',
                items: [
                    {
                        label: () => (
                            <SqlVisualizationPicker
                                query={sqlQuery}
                                columns={columns}
                                types={types}
                                result={result}
                                persistDisplayOptions={sqlPersist}
                            />
                        ),
                    },
                ],
            },
        ]
    }, [sqlQuery, columns, types, result, sqlPersist])

    if (picker?.kind === 'sql') {
        return sqlSection
    }

    if (picker?.kind === 'trends') {
        return TRENDS_SECTION
    }

    return []
}
