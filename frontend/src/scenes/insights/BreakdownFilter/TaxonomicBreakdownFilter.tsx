import React from 'react'
import { Space, Tag } from 'antd'
import { Breakdown, BreakdownType, FilterType, InsightType } from '~/types'
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
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

const isAllCohort = (t: number | string): t is string => typeof t === 'string' && t == 'all'

const isCohort = (t: number | string): t is number => typeof t === 'number'

const isCohortBreakdown = (t: number | string): t is number | string => isAllCohort(t) || isCohort(t)

const isPersonEventOrGroup = (t: number | string): t is string => typeof t === 'string' && t !== 'all'

export function BreakdownFilter({ filters, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdowns, breakdown_type } = filters
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)
    const { cohorts } = useValues(cohortsModel)

    let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
    if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
        breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
    }

    const hasSelectedBreakdown = breakdown && typeof breakdown === 'string'

    const multiPropertyBreakdownIsEnabled =
        filters.insight === InsightType.FUNNELS &&
        featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES] &&
        preflight?.is_clickhouse_enabled //breakdown is not available on postgres anyway but for completeness is checked here

    const breakdownArray = multiPropertyBreakdownIsEnabled
        ? (breakdowns || []).map((b) => b.property) // for now we ignore the breakdowns' type
        : (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b): b is string | number => !!b)

    const breakdownParts = breakdownArray.map((b) => (isNaN(Number(b)) ? b : Number(b)))

    const onCloseFor = (t: string | number, index: number): (() => void) => {
        return () => {
            if (isCohortBreakdown(t)) {
                const newParts = breakdownParts.filter((_, i): _ is string | number => i !== index)
                if (newParts.length === 0) {
                    setFilters({ breakdown: null, breakdown_type: null })
                } else {
                    setFilters({ breakdown: newParts, breakdown_type: 'cohort' })
                }
            } else {
                if (multiPropertyBreakdownIsEnabled) {
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
                    setFilters({ breakdown: undefined, breakdown_type: null })
                }
            }
        }
    }

    const tags = !breakdown_type
        ? []
        : breakdownArray.map((t, index) => (
              <Tag
                  className="taxonomic-breakdown-filter tag-pill"
                  key={t}
                  closable={true}
                  onClose={onCloseFor(t, index)}
              >
                  {isPersonEventOrGroup(t) && <PropertyKeyInfo value={t} />}
                  {isAllCohort(t) && <PropertyKeyInfo value={'All Users'} />}
                  {isCohort(t) && (
                      <PropertyKeyInfo value={cohorts.filter((c) => c.id == t)[0]?.name || `Cohort ${t}`} />
                  )}
              </Tag>
          ))

    const onChange = (changedBreakdown: TaxonomicFilterValue, groupType: TaxonomicFilterGroupType): void => {
        const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(groupType) as BreakdownType

        if (changedBreakdownType) {
            let newFilters: Partial<FilterType>
            if (multiPropertyBreakdownIsEnabled) {
                newFilters = {
                    breakdowns: [...breakdownParts, changedBreakdown]
                        .filter((b): b is string | number => !!b)
                        .map((b) => ({ property: b, type: changedBreakdownType })),
                    breakdown_type: changedBreakdownType,
                }
            } else {
                newFilters = {
                    breakdown:
                        groupType === TaxonomicFilterGroupType.CohortsWithAllUsers
                            ? [...breakdownParts, changedBreakdown].filter((b): b is string | number => !!b)
                            : changedBreakdown,
                    breakdown_type: changedBreakdownType,
                }
            }
            setFilters(newFilters)
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
