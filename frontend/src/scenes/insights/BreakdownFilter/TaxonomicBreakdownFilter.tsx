import { useValues } from 'kea'
import { cohortsModel } from '~/models/cohortsModel'
import React, { useState } from 'react'
import { Button, Tooltip } from 'antd'
import { BreakdownType, FilterType, ViewType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export interface TaxonomicBreakdownFilterProps {
    filters: Partial<FilterType>
    onChange: (breakdown: string, breakdownType: BreakdownType) => void
}

export function TaxonomicBreakdownFilter({ filters, onChange }: TaxonomicBreakdownFilterProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)
    const { breakdown, breakdown_type, insight } = filters
    const [open, setOpen] = useState(false)
    let label = breakdown

    if (breakdown_type === 'cohort' && breakdown) {
        label = cohorts.filter((c) => c.id == breakdown)[0]?.name || `Cohort #${breakdown}`
    }

    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    value={breakdown}
                    groupType={propertyFilterTypeToTaxonomicFilterType(breakdown_type)}
                    onChange={(groupType, value) => {
                        const filterType = taxonomicFilterTypeToPropertyFilterType(groupType)
                        if (value && filterType) {
                            onChange(value.toString(), filterType as BreakdownType)
                            setOpen(false)
                        }
                    }}
                    groupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.Cohorts,
                    ]}
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
                        <PropertyKeyInfo value={label || 'Add breakdown'} />
                    </Button>
                </Tooltip>
            )}
        </Popup>
    )
}
