import { useActions, useValues } from 'kea'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

type TaxonomicBreakdownPopoverProps = {
    open: boolean
    setOpen: (open: boolean) => void
    children: React.ReactElement
}

export const TaxonomicBreakdownPopover = ({ open, setOpen, children }: TaxonomicBreakdownPopoverProps): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { allEventNames } = useValues(insightVizDataLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { taxonomicBreakdownType, includeSessions } = useValues(taxonomicBreakdownFilterLogic)

    const { breakdownFilter, currentDataWarehouseSchemaColumns } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.CohortsWithAllUsers,
        ...(includeSessions ? [TaxonomicFilterGroupType.SessionProperties] : []),
        TaxonomicFilterGroupType.HogQLExpression,
        TaxonomicFilterGroupType.DataWarehouseProperties,
        TaxonomicFilterGroupType.DataWarehousePersonProperties,
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
                    schemaColumns={currentDataWarehouseSchemaColumns}
                />
            }
            visible={open}
            onClickOutside={() => setOpen(false)}
        >
            {children}
        </Popover>
    )
}
