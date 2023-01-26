import { useValues } from 'kea'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { Breakdown, ChartDisplayType, FilterType, InsightType, TrendsFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { onFilterChange, isURLNormalizeable } from './taxonomicBreakdownFilterUtils'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    useMultiBreakdown?: boolean
}

export const isAllCohort = (t: number | string): t is string => typeof t === 'string' && t == 'all'

export const isCohort = (t: number | string): t is number => typeof t === 'number'

export const isCohortBreakdown = (t: number | string): t is number | string => isAllCohort(t) || isCohort(t)

export const isPersonEventOrGroup = (t: number | string): t is string => typeof t === 'string' && t !== 'all'

export function TaxonomicBreakdownFilter({
    filters,
    setFilters,
    useMultiBreakdown = false,
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdowns, breakdown_type } = filters
    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)

    let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
    if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
        breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
    }

    const hasSelectedBreakdown = breakdown && typeof breakdown === 'string'

    const breakdownArray = useMultiBreakdown
        ? (breakdowns || []).map((b) => b.property)
        : (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b): b is string | number => !!b)

    const breakdownParts = breakdownArray.map((b) => (isNaN(Number(b)) ? b : Number(b)))

    const onCloseFor = setFilters
        ? (t: string | number, index: number): (() => void) => {
              return () => {
                  if (isCohortBreakdown(t)) {
                      const newParts = breakdownParts.filter((_, i): _ is string | number => i !== index)
                      if (newParts.length === 0) {
                          setFilters({ breakdown: null, breakdown_type: null })
                      } else {
                          setFilters({ breakdown: newParts, breakdown_type: 'cohort' })
                      }
                  } else {
                      if (useMultiBreakdown) {
                          if (!breakdown_type) {
                              console.error(new Error(`Unknown breakdown_type: "${breakdown_type}"`))
                          } else {
                              const newParts = breakdownParts.filter((_, i) => i !== index)
                              setFilters({
                                  breakdowns: newParts.map(
                                      (np): Breakdown => ({
                                          property: np,
                                          type: breakdown_type,
                                          normalize_url: isURLNormalizeable(np.toString()),
                                      })
                                  ),
                                  breakdown_type: breakdown_type,
                              })
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
          }
        : undefined

    const tags = !breakdown_type
        ? []
        : breakdownArray.map((t, index) => {
              const key = `${t}-${index}`
              const propertyDefinition = getPropertyDefinition(t)
              const isPropertyHistogramable = !useMultiBreakdown && !!propertyDefinition?.is_numerical

              return (
                  <BreakdownTag
                      key={key}
                      logicKey={key}
                      isHistogramable={isPropertyHistogramable}
                      isURLNormalizeable={isURLNormalizeable(propertyDefinition?.name || '')}
                      breakdown={t}
                      onClose={onCloseFor ? onCloseFor(t, index) : undefined}
                      filters={filters}
                      setFilters={setFilters}
                  />
              )
          })

    const onChange = setFilters
        ? onFilterChange({
              useMultiBreakdown,
              breakdownParts,
              setFilters,
              getPropertyDefinition: getPropertyDefinition,
          })
        : undefined

    return (
        <div className="flex flex-wrap gap-2 items-center">
            {tags}
            {onChange && (!hasSelectedBreakdown || useMultiBreakdown) ? (
                <TaxonomicBreakdownButton
                    breakdownType={breakdownType}
                    onChange={onChange}
                    includeSessions={filters.insight === InsightType.TRENDS}
                />
            ) : null}
        </div>
    )
}
