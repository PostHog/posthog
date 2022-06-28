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
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { featureFlags } = useValues(featureFlagsLogic)

    const taxonomicGroupTypes = onlyCohorts
        ? [TaxonomicFilterGroupType.CohortsWithAllUsers]
        : [
              TaxonomicFilterGroupType.EventProperties,
              TaxonomicFilterGroupType.PersonProperties,
              ...groupsTaxonomicTypes,
              TaxonomicFilterGroupType.CohortsWithAllUsers,
          ].concat(featureFlags[FEATURE_FLAGS.SESSION_ANALYSIS] ? [TaxonomicFilterGroupType.Sessions] : [])

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
                    eventNames={allEventNames}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                />
            }
            visible={open}
            onClickOutside={() => setOpen(false)}
        >
            <Button
                type={buttonType}
                icon={<PlusCircleOutlined />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                className="taxonomic-breakdown-filter tag-button"
            >
                <PropertyKeyInfo
                    value={
                        breakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers ? 'Add cohort' : 'Add breakdown'
                    }
                />
            </Button>
        </Popup>
    )
}
