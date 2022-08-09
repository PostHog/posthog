import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { groupsModel } from '~/models/groupsModel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { EditorFilterProps, FilterType, InsightType } from '~/types'
import { alphabet } from 'lib/utils'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'

export function TrendsSteps({ insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { filters } = useValues(trendsLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const propertiesTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        ...(filters.insight === InsightType.TRENDS ? [TaxonomicFilterGroupType.Sessions] : []),
    ]
    return (
        <>
            {filters.insight === InsightType.LIFECYCLE && (
                <div className="mb-2">
                    Showing <b>Unique users</b> who did
                </div>
            )}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
                typeKey={`trends_${InsightType.TRENDS}`}
                buttonCopy="Add graph series"
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    filters.insight === InsightType.LIFECYCLE ||
                    (filters.display && SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display))
                        ? 1
                        : alphabet.length
                }
                mathAvailability={
                    filters.insight === InsightType.LIFECYCLE
                        ? MathAvailability.None
                        : filters.insight === InsightType.STICKINESS
                        ? MathAvailability.ActorsOnly
                        : MathAvailability.All
                }
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
            />
        </>
    )
}
