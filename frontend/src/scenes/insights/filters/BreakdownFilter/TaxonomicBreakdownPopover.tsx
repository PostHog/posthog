import { useActions, useValues } from 'kea'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

type TaxonomicBreakdownPopoverProps = {
    open: boolean
    setOpen: (open: boolean) => void
    children: React.ReactElement
}

export const TaxonomicBreakdownPopover = ({ open, setOpen, children }: TaxonomicBreakdownPopoverProps): JSX.Element => {
    const { allEventNames } = useValues(insightLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { taxonomicBreakdownType, includeSessions } = useValues(taxonomicBreakdownFilterLogic)

    const { breakdownFilter } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    const taxonomicGroupTypes = [
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
                    value={breakdownFilter?.breakdown as TaxonomicFilterValue}
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
            {children}
        </Popover>
    )
}
