import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { EntityTypes, FilterType } from '~/types'

import { exclusionFiltersToNodes } from './exclusionFilterUtils'
import { ExclusionRow } from './ExclusionRow'
import { ExclusionRowSuffix } from './ExclusionRowSuffix'

export function FunnelExclusionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { exclusionFilters, exclusionDefaultStepRange, isFunnelWithEnoughSteps } = useValues(
        funnelDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const ref = useRef(null)

    const setFilters = (filters: Partial<FilterType>): void => {
        updateInsightFilter({ exclusions: exclusionFiltersToNodes(filters) })
    }

    const typeKey = `${keyForInsightLogicProps('new')(insightProps)}-FunnelExclusionsFilter`

    return (
        <div data-attr="funnel-exclusions-filter">
            <ActionFilter
                ref={ref}
                setFilters={setFilters}
                filters={exclusionFilters}
                typeKey={typeKey}
                addFilterDefaultOptions={{
                    id: '$pageview',
                    name: '$pageview',
                    type: EntityTypes.EVENTS,
                    funnel_from_step: exclusionDefaultStepRange.funnelFromStep,
                    funnel_to_step: exclusionDefaultStepRange.funnelToStep,
                }}
                disabled={!isFunnelWithEnoughSteps}
                buttonCopy="Add exclusion"
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                mathAvailability={MathAvailability.None}
                hideFilter
                hideRename
                hideDeleteBtn
                seriesIndicatorType="alpha"
                renderRow={(props) => <ExclusionRow {...props} />}
                customRowSuffix={(props) => <ExclusionRowSuffix typeKey={typeKey} {...props} />}
                filtersLeftPadding={true}
            />
        </div>
    )
}
