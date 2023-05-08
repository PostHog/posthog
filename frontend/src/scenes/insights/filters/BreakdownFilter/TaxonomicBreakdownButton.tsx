import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export interface TaxonomicBreakdownButtonProps {
    onlyCohorts?: boolean
}

export function TaxonomicBreakdownButton({ onlyCohorts }: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { taxonomicBreakdownType, includeSessions } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic)

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
                            addBreakdown(value, taxonomicGroup)
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
