import { useValues } from 'kea'
import { TaxonomicBreakdownButton } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownButton'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartDisplayType, FilterType, InsightType, TrendsFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'
import './TaxonomicBreakdownFilter.scss'
import { onFilterChange, isURLNormalizeable } from './taxonomicBreakdownFilterUtils'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { isCohortBreakdown } from './taxonomicBreakdownFilterUtils'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function TaxonomicBreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdown_type } = filters
    const { getPropertyDefinition } = useValues(propertyDefinitionsModel)

    const { hasSelectedBreakdown, taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic({ filters }))

    const breakdownArray = (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b): b is string | number => !!b)

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

    const tags = !breakdown_type
        ? []
        : breakdownArray.map((t, index) => {
              const key = `${t}-${index}`
              const propertyDefinition = getPropertyDefinition(t)
              const isPropertyHistogramable = !!propertyDefinition?.is_numerical

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
              breakdownParts,
              setFilters,
              getPropertyDefinition: getPropertyDefinition,
          })
        : undefined

    return (
        <div className="flex flex-wrap gap-2 items-center">
            {tags}
            {onChange && !hasSelectedBreakdown ? (
                <TaxonomicBreakdownButton
                    breakdownType={taxonomicBreakdownType}
                    onChange={onChange}
                    includeSessions={filters.insight === InsightType.TRENDS}
                />
            ) : null}
        </div>
    )
}
