import { useActions, useValues } from 'kea'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function CompareEditorFilter(): JSX.Element | null {
    const { insightProps, canEditInsight, editingDisabledReason } = useValues(insightLogic)
    const { compareFilter, supportsCompare } = useValues(insightVizDataLogic(insightProps))
    const { updateCompareFilter } = useActions(insightVizDataLogic(insightProps))
    return (
        <div className="px-2 pb-2">
            <CompareFilter
                compareFilter={compareFilter}
                updateCompareFilter={updateCompareFilter}
                disabled={!canEditInsight || !supportsCompare}
                disableReason={editingDisabledReason ?? undefined}
            />
        </div>
    )
}
