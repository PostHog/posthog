import { useValues } from 'kea'
import { cohortsModel } from '~/models/cohortsModel'
import React, { useState } from 'react'
import { Button, Row, Tooltip } from 'antd'
import { BreakdownType, FilterType, InsightType, ViewType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { CloseButton } from 'lib/components/CloseButton'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    onChange: (value: string | number | number[] | null, groupType: BreakdownType | null) => void
}

export interface TaxonomicBreakdownButtonProps {
    breakdown?: string | number | null
    breakdownType?: TaxonomicFilterGroupType
    insight?: InsightType
    onChange: (breakdown: string | number, groupType: TaxonomicFilterGroupType) => void
    onlyCohorts?: boolean
}

export function TaxonomicBreakdownFilter({ filters, onChange }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { breakdown, breakdown_type, insight } = filters
    const breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)

    if (breakdownType === TaxonomicFilterGroupType.Cohorts && breakdown) {
        const breakdownParts = (Array.isArray(breakdown) ? breakdown : [breakdown])
            .filter((b) => !!b)
            .map((b) => parseInt(`${b}`))

        return (
            <>
                {[...breakdownParts, 0].map((breakdownPart, index) => (
                    <Row key={index} style={{ marginBottom: 8 }}>
                        <TaxonomicBreakdownButton
                            onlyCohorts={index > 0 || breakdownParts.length > 1}
                            breakdown={breakdownPart}
                            breakdownType={breakdownType}
                            insight={insight}
                            onChange={(changedBreakdown) => {
                                const fullChangedBreakdown = [...breakdownParts, '']
                                    .map((b, i) => (i === index ? changedBreakdown : b))
                                    .filter((b) => !!b)
                                    .map((b) => parseInt(`${b}`))
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
            breakdown={Array.isArray(breakdown) ? breakdown[0] : breakdown}
            breakdownType={breakdownType}
            insight={insight}
            onChange={(changedBreakdown, groupType) => {
                const changedBreakdownType = taxonomicFilterTypeToPropertyFilterType(groupType) as BreakdownType
                if (changedBreakdownType) {
                    onChange(changedBreakdown, changedBreakdownType)
                }
            }}
        />
    )
}

export function TaxonomicBreakdownButton({
    breakdown,
    breakdownType,
    insight,
    onChange,
    onlyCohorts,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)
    const [open, setOpen] = useState(false)

    let label = breakdown ? breakdown.toString() : null
    if (breakdownType === TaxonomicFilterGroupType.Cohorts && breakdown) {
        label = cohorts.filter((c) => c.id == breakdown)[0]?.name || `Cohort #${breakdown}`
    }

    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    value={breakdown}
                    groupType={breakdownType}
                    onChange={(groupType, value) => {
                        if (value) {
                            onChange(value.toString(), groupType)
                            setOpen(false)
                        }
                    }}
                    groupTypes={
                        onlyCohorts
                            ? [TaxonomicFilterGroupType.Cohorts]
                            : [
                                  TaxonomicFilterGroupType.EventProperties,
                                  TaxonomicFilterGroupType.PersonProperties,
                                  TaxonomicFilterGroupType.Cohorts,
                              ]
                    }
                />
            }
            placement={'bottom-start'}
            fallbackPlacements={['bottom-end']}
            visible={open}
            onClickOutside={() => setOpen(false)}
        >
            {({ setRef }) => (
                <Tooltip
                    title={
                        insight === ViewType.STICKINESS &&
                        'Break down by is not yet available in combination with Stickiness'
                    }
                >
                    <Button
                        shape="round"
                        type={breakdown ? 'primary' : 'default'}
                        disabled={insight === ViewType.STICKINESS || insight === ViewType.LIFECYCLE}
                        data-attr="add-breakdown-button"
                        style={label ? { color: '#fff' } : {}}
                        onClick={() => setOpen(!open)}
                        ref={setRef}
                    >
                        <PropertyKeyInfo value={label || (onlyCohorts ? 'Add cohort' : 'Add breakdown')} />
                    </Button>
                </Tooltip>
            )}
        </Popup>
    )
}
