import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { legacyEntityToNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { ActionsNode, EventsNode } from '~/queries/schema/schema-general'
import { ActionFilter as ActionFilterType, EntityTypes, FilterType } from '~/types'

import { ExclusionRow } from './ExclusionRow'
import { ExclusionRowSuffix } from './ExclusionRowSuffix'

export function FunnelExclusionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { exclusionFilters, exclusionDefaultStepRange, isFunnelWithEnoughSteps } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const ref = useRef(null)

    const setFilters = (filters: Partial<FilterType>): void => {
        const exclusions = filters.events?.map((entity) => {
            const baseEntity = legacyEntityToNode(entity as ActionFilterType, true, MathAvailability.None) as
                | EventsNode
                | ActionsNode
            return { ...baseEntity, funnelFromStep: entity.funnel_from_step, funnelToStep: entity.funnel_to_step }
        })
        updateInsightFilter({ exclusions })
    }

    const typeKey = `${keyForInsightLogicProps('new')(insightProps)}-FunnelExclusionsFilter`

    return (
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
            actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
            mathAvailability={MathAvailability.None}
            hideFilter
            hideRename
            hideDeleteBtn
            seriesIndicatorType="alpha"
            renderRow={(props) => <ExclusionRow {...props} />}
            customRowSuffix={(props) => <ExclusionRowSuffix typeKey={typeKey} {...props} />}
            filtersLeftPadding={true}
        />
    )
}
