import React from 'react'
import { Row } from 'antd'
import { BreakdownType, FilterType } from '~/types'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { CloseButton } from 'lib/components/CloseButton'
import { TaxonomicBreakdownButton } from 'scenes/insights/BreakdownFilter/TaxonomicBreakdownButton'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    onChange: (value: string | number | (string | number)[] | null, groupType: BreakdownType | null) => void
}

export function BreakdownFilter({ filters, onChange }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdown_type } = filters

    let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
    if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
        breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
    }

    if (breakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers && breakdown) {
        const breakdownParts = (Array.isArray(breakdown) ? breakdown : [breakdown])
            .filter((b) => !!b)
            .map((b) => (b === 'all' ? b : parseInt(`${b}`)))

        return (
            <>
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
                        {breakdownPart ? (
                            <CloseButton
                                onClick={() => {
                                    const newParts = breakdownParts.filter((_, i) => i !== index)
                                    if (newParts.length === 0) {
                                        onChange(null, null)
                                    } else {
                                        onChange(newParts, 'cohort')
                                    }
                                }}
                                style={{ marginTop: 4, marginLeft: 5 }}
                            />
                        ) : null}
                    </Row>
                ))}
            </>
        )
    }

    return (
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
    )
}
