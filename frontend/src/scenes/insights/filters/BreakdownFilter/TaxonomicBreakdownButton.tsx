import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { BreakdownFilter } from '~/queries/schema'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
export interface TaxonomicBreakdownButtonProps {
    breakdownFilter?: BreakdownFilter
    onChange: (breakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup) => void
    onlyCohorts?: boolean
    includeSessions?: boolean
}

export function TaxonomicBreakdownButton({
    breakdownFilter,
    onChange,
    onlyCohorts,
    includeSessions,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    let taxonomicBreakdownType = propertyFilterTypeToTaxonomicFilterType(breakdownFilter?.breakdown_type)
    if (taxonomicBreakdownType === TaxonomicFilterGroupType.Cohorts) {
        taxonomicBreakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
    }

    const taxonomicGroupTypes = onlyCohorts
        ? [TaxonomicFilterGroupType.CohortsWithAllUsers]
        : [
              TaxonomicFilterGroupType.EventProperties,
              TaxonomicFilterGroupType.PersonProperties,
              TaxonomicFilterGroupType.EventFeatureFlags,
              ...groupsTaxonomicTypes,
              TaxonomicFilterGroupType.CohortsWithAllUsers,
              ...(includeSessions ? [TaxonomicFilterGroupType.Sessions] : []),
              TaxonomicFilterGroupType.HogQLExpression,
          ]

    return (
        <Popover
            overlay={
                <TaxonomicFilter
                    groupType={taxonomicBreakdownType}
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
                sideIcon={null}
            >
                <PropertyKeyInfo
                    value={
                        taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                            ? 'Add cohort'
                            : 'Add breakdown'
                    }
                />
            </LemonButton>
        </Popover>
    )
}
