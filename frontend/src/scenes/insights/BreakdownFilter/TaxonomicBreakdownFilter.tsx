import React from 'react'
import { Row, Tag } from 'antd'
import { BreakdownType, FilterType } from '~/types'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicBreakdownButton } from 'scenes/insights/BreakdownFilter/TaxonomicBreakdownButton'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useValues } from 'kea'
import { cohortsModel } from '~/models/cohortsModel'
import './TaxonomicBreakdownFilter.scss'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    onChange: (value: string | number | (string | number)[] | null, groupType: BreakdownType | null) => void
    setFilters: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export function BreakdownFilter({ filters, onChange, setFilters }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdown_type } = filters

    let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
    if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
        breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
    }

    /**
     * this is a list of "tags" representing breakdowns each of which can be removed followed by a button to add more
     * if the tag is a cohort there can be zero to many in the list
     * if the tag is a breakdown there can be zero or one in the list
     */

    const breakdownArray = (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b) => !!b)
    const breakdownParts = breakdownArray.map((b) => (b === 'all' ? b : parseInt(`${b}`)))
    const { cohorts } = useValues(cohortsModel)
    const tags = breakdownArray
        .filter((b) => !!b)
        .map((t, index) => {
            const onClose =
                typeof t === 'string' && t !== 'all'
                    ? () => setFilters({ breakdown: undefined, breakdown_type: null })
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

    if (breakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers && breakdown) {
        return (
            <>
                {tags}
                {[...breakdownParts, 0].map((breakdownPart, index) => (
                    <Row key={index} style={{ marginBottom: 8 }}>
                        <TaxonomicBreakdownButton
                            onlyCohorts={index > 0 || breakdownParts.length > 1}
                            breakdown={breakdownPart}
                            breakdownType={breakdownType}
                            onChange={(changedBreakdown) => {
                                const fullChangedBreakdown = [...breakdownParts, ''] // add empty element in teh end we could change it in `map`
                                    .map((b, i) => (i === index ? changedBreakdown : b))
                                    .filter((b) => !!b)
                                    .map((b) => (b === 'all' ? b : parseInt(`${b}`)))

                                onChange(fullChangedBreakdown, 'cohort')
                            }}
                        />
                    </Row>
                ))}
            </>
        )
    }

    return (
        <>
            {tags}
            <TaxonomicBreakdownButton
                breakdown={(Array.isArray(breakdown) ? breakdown[0] : breakdown) || undefined}
                breakdownType={breakdownType}
                onChange={(changedBreakdown, groupType) => {
                    const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(groupType) as BreakdownType
                    if (changedBreakdownType) {
                        if (groupType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
                            onChange([changedBreakdown], changedBreakdownType)
                        } else {
                            onChange(changedBreakdown, changedBreakdownType)
                        }
                    }
                }}
            />
        </>
    )
}
