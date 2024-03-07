import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS, SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { alphabet } from 'lib/utils'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { groupsModel } from '~/models/groupsModel'
import { FunnelsQuery, LifecycleQuery, StickinessQuery, TrendsQuery } from '~/queries/schema'
import { isInsightQueryNode } from '~/queries/utils'
import { FilterType } from '~/types'

import { actionsAndEventsToSeries } from '../InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'

export function TrendsSeries(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, isTrends, isLifecycle, isStickiness, display, hasFormula } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(isTrends ? [TaxonomicFilterGroupType.Sessions] : []),
        TaxonomicFilterGroupType.HogQLExpression,
        TaxonomicFilterGroupType.DataWarehouseProperties,
    ]

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const filters = queryNodeToFilter(querySource)
    const mathAvailability = isLifecycle
        ? MathAvailability.None
        : isStickiness
        ? MathAvailability.ActorsOnly
        : MathAvailability.All

    return (
        <>
            {isLifecycle && (
                <div className="leading-6">
                    Showing <b>Unique users</b> who did
                </div>
            )}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({ series: actionsAndEventsToSeries(payload as any, true, mathAvailability) } as
                        | TrendsQuery
                        | FunnelsQuery
                        | StickinessQuery
                        | LifecycleQuery)
                }}
                typeKey={`${keyForInsightLogicProps('new')(insightProps)}-TrendsSeries`}
                buttonCopy={`Add graph ${hasFormula ? 'variable' : 'series'}`}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    (display && SINGLE_SERIES_DISPLAY_TYPES.includes(display) && !hasFormula) || isLifecycle
                        ? 1
                        : alphabet.length
                }
                mathAvailability={mathAvailability}
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                actionsTaxonomicGroupTypes={
                    featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE] && featureFlags[FEATURE_FLAGS.HOGQL_INSIGHTS_TRENDS]
                        ? [
                              TaxonomicFilterGroupType.Events,
                              TaxonomicFilterGroupType.Actions,
                              TaxonomicFilterGroupType.DataWarehouse,
                          ]
                        : [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
                }
            />
        </>
    )
}
