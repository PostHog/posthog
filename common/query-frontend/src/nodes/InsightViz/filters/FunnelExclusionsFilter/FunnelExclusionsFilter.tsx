import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { funnelDataLogic } from '@posthog/query-frontend/nodes/FunnelsQuery/funnelDataLogic'
import { legacyEntityToNode } from '@posthog/query-frontend/nodes/InsightQuery/utils/filtersToQueryNode'
import { ActionFilter } from '@posthog/query-frontend/nodes/InsightViz/filters/ActionFilter/ActionFilter'
import { MathAvailability } from '@posthog/query-frontend/nodes/InsightViz/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { keyForInsightLogicProps } from '@posthog/query-frontend/nodes/InsightViz/sharedUtils'
import { ActionsNode, EventsNode } from '@posthog/query-frontend/schema/schema-general'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ActionFilter as ActionFilterType, EntityTypes, FilterType } from '~/types'

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
        </div>
    )
}
