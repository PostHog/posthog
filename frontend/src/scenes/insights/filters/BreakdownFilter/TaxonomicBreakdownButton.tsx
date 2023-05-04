import { useState } from 'react'
import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function TaxonomicBreakdownButton(): JSX.Element | null {
    const [open, setOpen] = useState(false)
    const { allEventNames } = useValues(insightLogic) // TODO: Convert to data exploration (see GlobalAndOrFilters)

    const { canAddBreakdown, taxonomicGroupType, taxonomicGroupTypes } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    if (!canAddBreakdown) {
        return null
    }

    return (
        <Popover
            overlay={
                <TaxonomicFilter
                    groupType={taxonomicGroupType}
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
                type="secondary"
                icon={<IconPlusMini color="var(--primary)" />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                className="taxonomic-breakdown-filter tag-button"
                sideIcon={null}
            >
                <PropertyKeyInfo
                    value={
                        taxonomicGroupType === TaxonomicFilterGroupType.CohortsWithAllUsers
                            ? 'Add cohort'
                            : 'Add breakdown'
                    }
                />
            </LemonButton>
        </Popover>
    )
}
