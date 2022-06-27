import { Tag } from 'antd'
import { useValues } from 'kea'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { TaxonomicBreakdownButton } from 'scenes/insights/Filters/BreakdownFilter/TaxonomicBreakdownButton'
import { cohortsModel } from '~/models/cohortsModel'
import { Breakdown, ChartDisplayType, FilterType } from '~/types'
import './TaxonomicBreakdownFilter.scss'
import { onFilterChange } from './taxonomicBreakdownFilterUtils'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    useMultiBreakdown?: boolean
}

const isAllCohort = (t: number | string): t is string => typeof t === 'string' && t == 'all'

const isCohort = (t: number | string): t is number => typeof t === 'number'

const isCohortBreakdown = (t: number | string): t is number | string => isAllCohort(t) || isCohort(t)

const isPersonEventOrGroup = (t: number | string): t is string => typeof t === 'string' && t !== 'all'

export function BreakdownFilter({
    filters,
    setFilters,
    useMultiBreakdown = false,
}: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdowns, breakdown_type } = filters
    const { cohortsById } = useValues(cohortsModel)

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
                                  breakdowns: newParts.map((np): Breakdown => ({ property: np, type: breakdown_type })),
                                  breakdown_type: breakdown_type,
                              })
                          }
                      } else {
                          setFilters({
                              breakdown: undefined,
                              breakdown_type: undefined,
                              // Make sure we are no longer in map view after removing the Country Code breakdown
                              display: filters.display !== ChartDisplayType.WorldMap ? filters.display : undefined,
                          })
                      }
                  }
              }
          }
        : undefined

    const tags = !breakdown_type
        ? []
        : breakdownArray.map((t, index) => (
              <Tag
                  className="taxonomic-breakdown-filter tag-pill"
                  key={t}
                  closable={!!setFilters}
                  onClose={onCloseFor?.(t, index)}
              >
                  {isPersonEventOrGroup(t) && <PropertyKeyInfo value={t} />}
                  {isAllCohort(t) && <PropertyKeyInfo value={'All Users'} />}
                  {isCohort(t) && <PropertyKeyInfo value={cohortsById[t]?.name || `Cohort ${t}`} />}
              </Tag>
          ))

    const onChange = setFilters ? onFilterChange({ useMultiBreakdown, breakdownParts, setFilters }) : undefined

    return (
        <div className="flex flex-wrap gap-05 items-center">
            {tags}
            {onChange && (!hasSelectedBreakdown || useMultiBreakdown) ? (
                <TaxonomicBreakdownButton breakdownType={breakdownType} onChange={onChange} />
            ) : null}
        </div>
    )
}
