import { useValues } from 'kea'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { Node } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'

import { SqlVisualizationPicker } from './SqlVisualizationPicker'
import { TrendsVisualizationPicker } from './TrendsVisualizationPicker'

export type VisualizationPickerKind = 'sql' | 'trends' | null

// Only insight types whose chart type is a single dropdown get a picker. Funnels, retention and paths
// each pick a chart through their own bespoke control, so they get nothing here.
export function resolveVisualizationPicker(
    query: Node | null,
    supportsDisplay: boolean,
    canPersist: boolean
): VisualizationPickerKind {
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
    const { insightProps } = useValues(insightLogic)
    const { supportsDisplay } = useValues(insightVizDataLogic(insightProps))

    const kind = resolveVisualizationPicker(query, supportsDisplay, !!persistDisplayOptions)

    if (kind === 'sql' && persistDisplayOptions && query && isDataVisualizationNode(query)) {
        return [
            {
                title: 'Visualization',
                items: [
                    {
                        label: () => (
                            <SqlVisualizationPicker
                                query={query}
                                insightData={insightData}
                                persistDisplayOptions={persistDisplayOptions}
                            />
                        ),
                    },
                ],
            },
        ]
    }

    if (kind === 'trends') {
        return [{ title: 'Visualization', items: [{ label: () => <TrendsVisualizationPicker /> }] }]
    }

    return []
}
