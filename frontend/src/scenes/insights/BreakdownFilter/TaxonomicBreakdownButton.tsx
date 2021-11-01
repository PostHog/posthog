import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Button } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PlusCircleOutlined } from '@ant-design/icons'

export interface TaxonomicBreakdownButtonProps {
    breakdownType?: TaxonomicFilterGroupType
    onChange: (breakdown: string | number, groupType: TaxonomicFilterGroupType) => void
    onlyCohorts?: boolean
}

export function TaxonomicBreakdownButton({
    breakdownType,
    onChange,
    onlyCohorts,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    groupType={breakdownType}
                    onChange={(groupType, value) => {
                        if (value) {
                            onChange(value, groupType)
                            setOpen(false)
                        }
                    }}
                    taxonomicGroupTypes={
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
                    type={'link'}
                    icon={<PlusCircleOutlined />}
                    data-attr="add-breakdown-button"
                    onClick={() => setOpen(!open)}
                    className="taxonomic-breakdown-filter tag-button"
                    ref={setRef}
                >
                    <PropertyKeyInfo
                        value={
                            breakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                                ? 'Add cohort'
                                : 'Add breakdown'
                        }
                    />
                </Button>
            )}
        </Popup>
    )
}
