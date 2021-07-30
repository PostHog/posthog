import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { useValues } from 'kea'
import { cohortsModel } from '~/models/cohortsModel'
import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Button } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PlusCircleOutlined } from '@ant-design/icons'

export interface TaxonomicBreakdownButtonProps {
    breakdown?: TaxonomicFilterValue
    breakdownType?: TaxonomicFilterGroupType
    onChange: (breakdown: string | number, groupType: TaxonomicFilterGroupType) => void
    onlyCohorts?: boolean
}

export function TaxonomicBreakdownButton({
    breakdown,
    breakdownType,
    onChange,
    onlyCohorts,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)
    const [open, setOpen] = useState(false)

    let label: string | null = breakdown ? `${breakdown}` : null

    if (breakdown && breakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
        label =
            breakdown === 'all'
                ? 'All Users'
                : cohorts.filter((c) => c.id == breakdown)[0]?.name || `Cohort ${breakdown}`
    }

    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    value={breakdown}
                    groupType={breakdownType}
                    onChange={(groupType, value) => {
                        if (value) {
                            onChange(value, groupType)
                            setOpen(false)
                        }
                    }}
                    groupTypes={
                        onlyCohorts
                            ? [TaxonomicFilterGroupType.CohortsWithAllUsers]
                            : [
                                  TaxonomicFilterGroupType.EventProperties,
                                  TaxonomicFilterGroupType.PersonProperties,
                                  TaxonomicFilterGroupType.CohortsWithAllUsers,
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
                <Button
                    type={breakdown ? 'primary' : 'link'}
                    icon={!breakdown ? <PlusCircleOutlined /> : undefined}
                    data-attr="add-breakdown-button"
                    style={breakdown ? { color: '#fff' } : { paddingLeft: 0 }}
                    onClick={() => setOpen(!open)}
                    ref={setRef}
                >
                    <PropertyKeyInfo value={label ?? (onlyCohorts ? 'Add cohort' : 'Add breakdown')} />
                </Button>
            )}
        </Popup>
    )
}
