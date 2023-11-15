import { useRef } from 'react'
import { useActions, useValues } from 'kea'
import useSize from '@react-hook/size'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FunnelExclusion, EntityTypes, FilterType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { ExclusionRowSuffix } from './ExclusionRowSuffix'
import { ExclusionRow } from './ExclusionRow'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function FunnelExclusionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { exclusionFilters, exclusionDefaultStepRange, isFunnelWithEnoughSteps } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const ref = useRef(null)
    const [width] = useSize(ref)
    const isVerticalLayout = !!width && width < 450 // If filter container shrinks below 500px, initiate verticality

    const setFilters = (filters: Partial<FilterType>): void => {
        const exclusions = (filters.events as FunnelExclusion[]).map((e) => ({
            ...e,
            funnel_from_step: e.funnel_from_step || exclusionDefaultStepRange.funnel_from_step,
            funnel_to_step: e.funnel_to_step || exclusionDefaultStepRange.funnel_to_step,
        }))
        updateInsightFilter({ exclusions })
    }

    return (
        <ActionFilter
            ref={ref}
            setFilters={setFilters}
            filters={exclusionFilters}
            typeKey={`${keyForInsightLogicProps('new')(insightProps)}-FunnelExclusionsFilter`}
            addFilterDefaultOptions={{
                id: '$pageview',
                name: '$pageview',
                type: EntityTypes.EVENTS,
                ...exclusionDefaultStepRange,
            }}
            disabled={!isFunnelWithEnoughSteps}
            buttonCopy="Add exclusion"
            actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
            mathAvailability={MathAvailability.None}
            hideFilter
            hideRename
            hideDeleteBtn
            seriesIndicatorType="alpha"
            renderRow={(props) => <ExclusionRow {...props} isVertical={isVerticalLayout} />}
            customRowSuffix={(props) => <ExclusionRowSuffix {...props} isVertical={isVerticalLayout} />}
        />
    )
}
