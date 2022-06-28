import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { Popup } from 'lib/components/Popup/Popup'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/components/icons'

export interface TaxonomicBreakdownButtonProps {
    breakdownType?: TaxonomicFilterGroupType
    onChange: (breakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup) => void
    onlyCohorts?: boolean
}

export function TaxonomicBreakdownButton({
    breakdownType,
    onChange,
    onlyCohorts,
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
            <LemonButton
                type={'secondary'}
                icon={<IconPlusMini color="var(--primary)" />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                className="taxonomic-breakdown-filter tag-button"
            >
                <PropertyKeyInfo
                    value={
                        breakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers ? 'Add cohort' : 'Add breakdown'
                    }
                />
            </LemonButton>
        </Popup>
    )
}
