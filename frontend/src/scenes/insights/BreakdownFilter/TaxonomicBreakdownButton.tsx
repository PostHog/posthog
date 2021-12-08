import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Button } from 'antd'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PlusCircleOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { ButtonType } from 'antd/lib/button'

export interface TaxonomicBreakdownButtonProps {
    breakdownType?: TaxonomicFilterGroupType
    onChange: (breakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup) => void
    onlyCohorts?: boolean
    buttonType?: ButtonType
}

export function TaxonomicBreakdownButton({
    breakdownType,
    onChange,
    onlyCohorts,
    buttonType = 'link',
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <Popup
            overlay={
                <TaxonomicFilter
                    groupType={breakdownType}
                    onChange={(taxonomicGroup, value) => {
                        if (value) {
                            onChange(value, taxonomicGroup)
                            setOpen(false)
                        }
                    }}
                    taxonomicGroupTypes={
                        onlyCohorts
                            ? [TaxonomicFilterGroupType.CohortsWithAllUsers]
                            : [
                                  TaxonomicFilterGroupType.EventProperties,
                                  TaxonomicFilterGroupType.PersonProperties,
                                  ...groupsTaxonomicTypes,
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
                    type={buttonType}
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
