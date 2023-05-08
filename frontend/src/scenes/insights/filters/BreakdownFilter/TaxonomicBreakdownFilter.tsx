import { useActions, useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartDisplayType, FilterType, InsightType, TrendsFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { isCohortBreakdown } from './taxonomicBreakdownFilterUtils'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function TaxonomicBreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)

    const { hasBreakdown, hasNonCohortBreakdown, taxonomicBreakdownType, breakdownArray, breakdownCohortArray } =
        useValues(taxonomicBreakdownFilterLogic({ filters, setFilters, getPropertyDefinition }))
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic({ filters, setFilters, getPropertyDefinition }))

    const onCloseFor = setFilters
        ? (breakdown: string | number): (() => void) => {
              return () => {
                  if (isCohortBreakdown(breakdown)) {
                      const newParts = breakdownCohortArray.filter((cohort) => cohort !== breakdown)
                      if (newParts.length === 0) {
                          setFilters({ breakdown: null, breakdown_type: null })
                      } else {
                          setFilters({ breakdown: newParts, breakdown_type: 'cohort' })
                      }
                  } else {
                      const newFilters: Partial<TrendsFilterType> = {
                          breakdown: undefined,
                          breakdown_type: undefined,
                          breakdown_histogram_bin_count: undefined,
                          // Make sure we are no longer in map view after removing the Country Code breakdown
                          display:
                              isTrendsFilter(filters) && filters.display !== ChartDisplayType.WorldMap
                                  ? filters.display
                                  : undefined,
                      }
                      setFilters(newFilters)
                  }
              }
          }
        : undefined

    const tags = !hasBreakdown
        ? []
        : breakdownArray.map((breakdown, index) => (
              <BreakdownTag
                  key={`${breakdown}-${index}`}
                  logicKey={`${breakdown}-${index}`}
                  breakdown={breakdown}
                  removeBreakdown={onCloseFor ? onCloseFor(breakdown) : undefined}
                  filters={filters}
                  setFilters={setFilters}
              />
          ))

    return (
        <div className="flex flex-wrap gap-2 items-center">
            {tags}
            {setFilters && !hasNonCohortBreakdown ? (
                <TaxonomicBreakdownButton
                    breakdownType={taxonomicBreakdownType}
                    addBreakdown={addBreakdown}
                    includeSessions={filters.insight === InsightType.TRENDS} // TODO: convert to data exploration
                />
            ) : null}
        </div>
    )
}
