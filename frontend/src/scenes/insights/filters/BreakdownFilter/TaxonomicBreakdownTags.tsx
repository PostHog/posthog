import { Breakdown, ChartDisplayType, TrendsFilterType } from '~/types'
import { BreakdownTag } from './BreakdownTag'

import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { isCohortBreakdown } from './taxonomicBreakdownFilterUtils'
import { isURLNormalizeable } from './taxonomicBreakdownFilterUtils'

export const TaxonomicBreakdownTags = () => {
    if (!breakdown_type) {
        return null
    }

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

    return (
        <>
            {breakdownArray.map((t, index) => {
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
            })}
        </>
    )
}
