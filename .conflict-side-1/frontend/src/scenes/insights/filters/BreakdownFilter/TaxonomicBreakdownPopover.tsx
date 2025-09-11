import { useActions, useValues } from 'kea'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { isInsightVizNode, isRetentionQuery } from '~/queries/utils'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

type TaxonomicBreakdownPopoverProps = {
    open: boolean
    setOpen: (open: boolean) => void
    children: React.ReactElement
    taxonomicType?: TaxonomicFilterGroupType
    breakdownType?: string
    breakdownValue?: string | number | null
}

export const TaxonomicBreakdownPopover = ({
    open,
    setOpen,
    children,
    taxonomicType,
    breakdownType,
    breakdownValue,
}: TaxonomicBreakdownPopoverProps): JSX.Element => {
    const { insightProps } = useValues(insightLogic)
    const { allEventNames, query } = useValues(insightVizDataLogic(insightProps))
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { includeSessions } = useValues(taxonomicBreakdownFilterLogic)

    const { currentDataWarehouseSchemaColumns } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown, replaceBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    let taxonomicGroupTypes: TaxonomicFilterGroupType[]
    if (isRetentionQuery(query) || (isInsightVizNode(query) && isRetentionQuery(query.source))) {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
        ]
    } else {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.EventFeatureFlags,
            TaxonomicFilterGroupType.EventMetadata,
            ...groupsTaxonomicTypes,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
            ...(includeSessions ? [TaxonomicFilterGroupType.SessionProperties] : []),
            TaxonomicFilterGroupType.HogQLExpression,
            TaxonomicFilterGroupType.DataWarehouseProperties,
            TaxonomicFilterGroupType.DataWarehousePersonProperties,
        ]
    }

    return (
        <Popover
            style={{ minHeight: '200px' }}
            overlay={
                <TaxonomicFilter
                    groupType={taxonomicType}
                    value={breakdownValue}
                    onChange={(taxonomicGroup, value) => {
                        if (breakdownValue && breakdownType) {
                            replaceBreakdown(
                                {
                                    value: breakdownValue,
                                    type: breakdownType,
                                },
                                {
                                    value,
                                    group: taxonomicGroup,
                                }
                            )
                        } else {
                            addBreakdown(value, taxonomicGroup)
                        }

                        setOpen(false)
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
