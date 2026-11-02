import { useActions, useValues } from 'kea'

import { EvaluationCompareItem } from './EvaluationCompareItem'
import { EvaluationCreateSlot } from './EvaluationCreateSlot'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/**
 * Every evaluation with results, as the chart's legend and picker in one. The ones that need attention come
 * first with a colored caption saying why, so no heading is needed to set them apart.
 */
export function EvaluationCompareList({ colors }: { colors: Map<string, string> }): JSX.Element {
    const { compareListRows, few } = useValues(evaluationsOverviewLogic)
    const { toggleCompared } = useActions(evaluationsOverviewLogic)

    return (
        <ul className="flex flex-col gap-0.5 max-h-96 overflow-y-auto pr-1">
            {compareListRows.map((row) => (
                <EvaluationCompareItem
                    key={row.id}
                    row={row}
                    color={colors.get(row.id)}
                    onToggle={() => toggleCompared(row.id)}
                />
            ))}
            {few && (
                // Leaves the arrow column empty, so the slot lines up with the rows above it.
                <li className="flex items-center gap-1 mt-1">
                    <EvaluationCreateSlot className="flex-1" />
                    <span aria-hidden className="w-6 shrink-0" />
                </li>
            )}
        </ul>
    )
}
