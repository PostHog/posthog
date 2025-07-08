import { useActions, useValues } from 'kea'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

export function Breakdown({ insightProps }: EditorFilterProps): JSX.Element {
    const { breakdownFilter, display, isTrends, isSingleSeries, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateBreakdownFilter, updateDisplay } = useActions(insightVizDataLogic(insightProps))

    return (
        <>
            <TaxonomicBreakdownFilter
                insightProps={insightProps}
                breakdownFilter={breakdownFilter}
                display={display}
                isTrends={isTrends}
                updateBreakdownFilter={updateBreakdownFilter}
                updateDisplay={updateDisplay}
                disabledReason={
                    !isSingleSeries && hasDataWarehouseSeries
                        ? 'Breakdowns are not allowed for multiple series types'
                        : undefined
                }
            />
        </>
    )
}
