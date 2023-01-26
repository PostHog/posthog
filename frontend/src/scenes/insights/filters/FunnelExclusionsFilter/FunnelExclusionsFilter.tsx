import { useRef } from 'react'
import { useActions, useValues } from 'kea'
import useSize from '@react-hook/size'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FunnelStepRangeEntityFilter, EntityTypes, FilterType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { FunnelsQuery } from '~/queries/schema'
import { ExclusionRowSuffix, ExclusionRowSuffixDataExploration } from './ExclusionRowSuffix'
import { ExclusionRow } from './ExclusionRow'

export function FunnelExclusionsFilterDataExploration(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { exclusionFilters, exclusionDefaultStepRange, querySource } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <FunnelExclusionsFilterComponent
            exclusionFilters={exclusionFilters}
            exclusionDefaultStepRange={exclusionDefaultStepRange}
            areFiltersValid={(querySource as FunnelsQuery).series.length > 1}
            setFilters={(filters) => {
                const exclusions = (filters.events as FunnelStepRangeEntityFilter[]).map((e) => ({
                    ...e,
                    funnel_from_step: e.funnel_from_step || exclusionDefaultStepRange.funnel_from_step,
                    funnel_to_step: e.funnel_to_step || exclusionDefaultStepRange.funnel_to_step,
                }))
                updateInsightFilter({ exclusions })
            }}
            isDataExploration
        />
    )
}

export function FunnelExclusionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { exclusionFilters, areFiltersValid, exclusionDefaultStepRange } = useValues(funnelLogic(insightProps))
    const { setEventExclusionFilters } = useActions(funnelLogic(insightProps))

    return (
        <FunnelExclusionsFilterComponent
            exclusionFilters={exclusionFilters}
            exclusionDefaultStepRange={exclusionDefaultStepRange}
            areFiltersValid={areFiltersValid}
            setFilters={setEventExclusionFilters}
        />
    )
}

type FunnelExclusionsFilterComponentProps = {
    exclusionFilters: FilterType
    exclusionDefaultStepRange: Omit<FunnelStepRangeEntityFilter, 'id' | 'name'>
    areFiltersValid: boolean
    setFilters: (filters: Partial<FilterType>) => void
    isDataExploration?: boolean
}

export function FunnelExclusionsFilterComponent({
    exclusionFilters,
    exclusionDefaultStepRange,
    areFiltersValid,
    setFilters,
    isDataExploration,
}: FunnelExclusionsFilterComponentProps): JSX.Element {
    const ref = useRef(null)
    const [width] = useSize(ref)
    const isVerticalLayout = !!width && width < 450 // If filter container shrinks below 500px, initiate verticality

    return (
        <ActionFilter
            ref={ref}
            setFilters={setFilters}
            filters={exclusionFilters}
            typeKey="funnel-exclusions-filter"
            addFilterDefaultOptions={{
                id: '$pageview',
                name: '$pageview',
                type: EntityTypes.EVENTS,
                ...exclusionDefaultStepRange,
            }}
            disabled={!areFiltersValid}
            buttonCopy="Add exclusion"
            actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
            mathAvailability={MathAvailability.None}
            hideFilter
            hideRename
            hideDeleteBtn
            seriesIndicatorType="alpha"
            renderRow={(props) => <ExclusionRow {...props} isVertical={isVerticalLayout} />}
            customRowSuffix={(props) =>
                isDataExploration ? (
                    <ExclusionRowSuffixDataExploration {...props} isVertical={isVerticalLayout} />
                ) : (
                    <ExclusionRowSuffix {...props} isVertical={isVerticalLayout} />
                )
            }
        />
    )
}
