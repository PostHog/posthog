import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function Breakdown({ insightProps }: EditorFilterProps): JSX.Element {
    const { breakdownFilter, display, isTrends, isFunnels } = useValues(insightVizDataLogic(insightProps))
    const { updateBreakdownFilter, updateDisplay } = useActions(insightVizDataLogic(insightProps))
    const editorPanelsEnabled = useFeatureFlag('PRODUCT_ANALYTICS_SIMPLE_EDITOR', 'test')

    return (
        <>
            <TaxonomicBreakdownFilter
                insightProps={insightProps}
                breakdownFilter={breakdownFilter}
                display={display}
                isTrends={isTrends}
                isFunnels={isFunnels}
                updateBreakdownFilter={updateBreakdownFilter}
                updateDisplay={updateDisplay}
                showLabel={!editorPanelsEnabled}
                showInlineOptions={editorPanelsEnabled}
            />
        </>
    )
}
