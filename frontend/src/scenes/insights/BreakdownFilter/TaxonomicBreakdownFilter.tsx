import React from 'react'
import { Space, Tag } from 'antd'
import { BreakdownType, FilterType, ViewType } from '~/types'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicBreakdownButton } from 'scenes/insights/BreakdownFilter/TaxonomicBreakdownButton'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useValues } from 'kea'
import { cohortsModel } from '~/models/cohortsModel'
import './TaxonomicBreakdownFilter.scss'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function BreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdown_type } = filters
    const { featureFlags } = useValues(featureFlagLogic)

    let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
    if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
        breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
    }

    const hasSelectedBreakdown = breakdown && typeof breakdown === 'string'

    const breakdownArray = (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b) => !!b)
    const breakdownParts = breakdownArray.map((b) => (isNaN(Number(b)) ? b : Number(b))).filter((b) => !!b)
    const { cohorts } = useValues(cohortsModel)

    const multiPropertyBreakdownIsEnabled =
        filters.insight === ViewType.FUNNELS && featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]

    const tags = breakdownArray
        .filter((b) => !!b)
        .map((t, index) => {
            const onClose =
                typeof t === 'string' && t !== 'all'
                    ? () => {
                          if (multiPropertyBreakdownIsEnabled) {
                              const newParts = breakdownParts.filter((_, i) => i !== index)
                              setFilters({ breakdown: newParts, breakdown_type: breakdown_type })
                          } else {
                              setFilters({ breakdown: undefined, breakdown_type: null })
                          }
                      }
                    : () => {
                          const newParts = breakdownParts.filter((_, i) => i !== index)
                          if (newParts.length === 0) {
                              setFilters({ breakdown: null, breakdown_type: null })
                          } else {
                              setFilters({ breakdown: newParts, breakdown_type: 'cohort' })
                          }
                      }
            return (
                <Tag className="taxonomic-breakdown-filter tag-pill" key={t} closable={true} onClose={onClose}>
                    {typeof t === 'string' && t !== 'all' && <PropertyKeyInfo value={t} />}
                    {typeof t === 'string' && t == 'all' && <PropertyKeyInfo value={'All Users'} />}
                    {typeof t === 'number' && (
                        <PropertyKeyInfo value={cohorts.filter((c) => c.id == t)[0]?.name || `Cohort ${t}`} />
                    )}
                </Tag>
            )
        })

    const onChange = multiPropertyBreakdownIsEnabled
        ? (changedBreakdown: TaxonomicFilterValue, groupType: TaxonomicFilterGroupType): void => {
              const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(groupType) as BreakdownType

              if (changedBreakdownType) {
                  const newFilters = {
                      breakdown: [...breakdownParts, changedBreakdown],
                      breakdown_type: changedBreakdownType,
                  }

                  setFilters(newFilters)
              }
          }
        : (changedBreakdown: TaxonomicFilterValue, groupType: TaxonomicFilterGroupType): void => {
              const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(groupType) as BreakdownType

              if (changedBreakdownType) {
                  setFilters({
                      breakdown:
                          groupType === TaxonomicFilterGroupType.CohortsWithAllUsers
                              ? [...breakdownParts, changedBreakdown]
                              : changedBreakdown,
                      breakdown_type: changedBreakdownType,
                  })
              }
          }
    return (
        <>
            <Space direction={'horizontal'} wrap={true}>
                {tags}
                {!hasSelectedBreakdown || multiPropertyBreakdownIsEnabled ? (
                    <TaxonomicBreakdownButton breakdownType={breakdownType} onChange={onChange} />
                ) : null}
            </Space>
        </>
    )
}
