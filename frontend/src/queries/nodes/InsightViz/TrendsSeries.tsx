// import { useActions, useValues } from 'kea'
import { useValues, useActions } from 'kea'
// import { trendsLogic } from 'scenes/trends/trendsLogic'
import { groupsModel } from '~/models/groupsModel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
// import { EditorFilterProps, FilterType, InsightType } from '~/types'
import { InsightType, FilterType, InsightLogicProps } from '~/types'
// import { alphabet } from 'lib/utils'
// import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
// import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
// import { LemonButton } from '@posthog/lemon-ui'
// import { Tooltip } from 'lib/components/Tooltip'
// import { IconCalculate } from 'lib/components/icons'
// import { isFilterWithDisplay, isLifecycleFilter, isStickinessFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'
import { TrendsQuery, FunnelsQuery, LifecycleQuery } from '~/queries/schema'
import { isLifecycleQuery, isUnimplementedQuery } from '~/queries/utils'
import { actionsAndEventsToSeries, queryNodeToFilter } from '../InsightQuery/queryNodeToFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

type TrendsSeriesProps = {
    insightProps: InsightLogicProps
}

export function TrendsSeries({ insightProps }: TrendsSeriesProps): JSX.Element | null {
    const dataLogic = insightDataLogic(insightProps)
    const { querySource } = useValues(dataLogic)
    const { setQuerySourceMerge } = useActions(dataLogic)
    // const { setFilters } = useActions(trendsLogic(insightProps))
    // const { filters, isFormulaOn } = useValues(trendsLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        // ...(isTrendsFilter(filters) ? [TaxonomicFilterGroupType.Sessions] : []),
    ]

    if (isUnimplementedQuery(querySource)) {
        return null
    }

    const filters = queryNodeToFilter(querySource)
    return (
        <>
            {isLifecycleQuery(querySource) && (
                <div className="leading-6">
                    Showing <b>Unique users</b> who did
                </div>
            )}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => {
                    setQuerySourceMerge({ series: actionsAndEventsToSeries(payload as any) } as
                        | TrendsQuery
                        | FunnelsQuery
                        | LifecycleQuery)
                }}
                typeKey={`trends_${InsightType.TRENDS}_data_exploration`}
                // buttonCopy={`Add graph ${isFormulaOn ? 'variable' : 'series'}`}
                buttonCopy="Add graph series"
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={1}
                // entitiesLimit={
                //     (isFilterWithDisplay(filters) &&
                //         filters.display &&
                //         SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display) &&
                //         !isFormulaOn) ||
                //     isLifecycleFilter(filters)
                //         ? 1
                //         : alphabet.length
                // }
                mathAvailability={MathAvailability.None}
                // mathAvailability={
                //     isLifecycleFilter(filters)
                //         ? MathAvailability.None
                //         : isStickinessFilter(filters)
                //         ? MathAvailability.ActorsOnly
                //         : MathAvailability.All
                // }
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
            />
        </>
    )
}

// export function TrendsSeriesLabel({ insightProps }: EditorFilterProps): JSX.Element {
//     const { filters, localFilters, isFormulaOn } = useValues(trendsLogic(insightProps))
//     const { setIsFormulaOn } = useActions(trendsLogic(insightProps))

//     const formulaModeButtonDisabled: boolean =
//         isFormulaOn &&
//         isTrendsFilter(filters) &&
//         !!filters.display &&
//         SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display) &&
//         localFilters.length > 1

//     return (
//         <div className="flex items-center justify-between w-full">
//             <span>{isFormulaOn ? 'Variables' : 'Series'}</span>
//             <Tooltip
//                 title={
//                     formulaModeButtonDisabled
//                         ? 'This chart type does not support multiple series, so in order to disable formula mode, remove variables or switch to a different chart type.'
//                         : 'Make your own formula the output of the insight with formula mode. Use graph series as variables.'
//                 }
//             >
//                 {/** The negative margin negates the button's effect on label sizing. */}
//                 <div style={{ margin: '-0.25rem 0' }}>
//                     <LemonButton
//                         size="small"
//                         onClick={() => setIsFormulaOn(!isFormulaOn)}
//                         disabled={formulaModeButtonDisabled}
//                         icon={<IconCalculate />}
//                         id="trends-formula-switch"
//                     >
//                         {isFormulaOn ? 'Disable' : 'Enable'} formula mode
//                     </LemonButton>
//                 </div>
//             </Tooltip>
//         </div>
//     )
// }
