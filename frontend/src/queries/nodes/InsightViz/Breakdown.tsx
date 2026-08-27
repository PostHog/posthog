import { useActions, useValues } from 'kea'

import {
    canAddBehavioralBreakdown,
    createBehavioralBreakdownSeries,
} from 'scenes/insights/filters/BreakdownFilter/behavioralBreakdown'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { FEATURE_FLAGS } from '~/lib/constants'
import { BehavioralPropertyFilter, EditorFilterProps } from '~/types'

export function Breakdown({ insightProps }: EditorFilterProps): JSX.Element {
    const { breakdownFilter, display, featureFlags, isTrends, isFunnels, querySource } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateBreakdownFilter, updateDisplay, updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const addBehavioralBreakdown = canAddBehavioralBreakdown(
        querySource,
        !!featureFlags[FEATURE_FLAGS.BEHAVIORAL_PROPERTY_FILTER]
    )
        ? (filter: BehavioralPropertyFilter): void => {
              updateQuerySource({ series: createBehavioralBreakdownSeries(querySource.series[0], filter) })
          }
        : undefined

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
                onAddBehavioralBreakdown={addBehavioralBreakdown}
                showLabel={false}
                showInlineOptions
            />
        </>
    )
}
