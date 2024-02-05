import useSize from '@react-hook/size'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useRef } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { legacyEntityToNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { ActionFilter as ActionFilterType, EntityTypes, FilterType, FunnelExclusionLegacy } from '~/types'

import { ExclusionRow } from './ExclusionRow'
import { ExclusionRowSuffix } from './ExclusionRowSuffix'

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
        const exclusions = filters.events?.map((entity: FunnelExclusionLegacy) => {
            const baseEntity = legacyEntityToNode(entity as ActionFilterType, false, MathAvailability.None)
            return { ...baseEntity, funnelFromStep: entity.funnel_from_step, funnelToStep: entity.funnel_to_step }
        })
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
