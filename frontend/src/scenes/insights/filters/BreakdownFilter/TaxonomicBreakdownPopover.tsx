import { useActions, useMountedLogic, useValues } from 'kea'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { hogql, isInsightVizNode, isRetentionQuery } from '~/queries/utils'

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
    // allEventNames resolves action series through actionsModel, which the shared insight logic does not mount
    useMountedLogic(actionsModel)
    const { insightProps } = useValues(insightLogic)
    const { allEventNames, query, hasDataWarehouseSeries, dataWarehouseSeriesTableNames, isTrends } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { databaseLoading } = useValues(databaseTableListLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { includeSessions, taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    const { currentDataWarehouseSchemaColumns } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown, replaceBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    let taxonomicGroupTypes: TaxonomicFilterGroupType[]
    if (hasDataWarehouseSeries) {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.DataWarehouseProperties,
            // A funnel evaluates a SQL expression breakdown on its events steps only. On a warehouse
            // step the breakdown column falls back to an empty value, so an all-warehouse funnel
            // collapses into one empty group, and on a mixed funnel the expression resolves against
            // `events`, where a warehouse column does not exist. Trends parses the expression in the
            // series' own scope, so the escape hatch works there.
            ...(isTrends ? [TaxonomicFilterGroupType.HogQLExpression] : []),
        ]
    } else if (taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
        taxonomicGroupTypes = [TaxonomicFilterGroupType.CohortsWithAllUsers]
    } else if (isRetentionQuery(query) || (isInsightVizNode(query) && isRetentionQuery(query.source))) {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.MCPProperties,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.EventFeatureFlags,
            ...groupsTaxonomicTypes,
            TaxonomicFilterGroupType.CohortsWithAllUsers,
            TaxonomicFilterGroupType.HogQLExpression,
            TaxonomicFilterGroupType.DataWarehousePersonProperties,
        ]
    } else {
        taxonomicGroupTypes = [
            // Only materializes when the insight has $mcp_* series in scope, so breakdowns
            // by e.g. tool name or error state lead with the known MCP schema.
            TaxonomicFilterGroupType.MCPProperties,
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
                    hogQLExpressionShowBreakdownLabelHint
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
                    metadataSource={
                        // Without this the SQL expression editor validates against the events table
                        // and marks every warehouse column as unknown.
                        dataWarehouseSeriesTableNames.length === 1
                            ? {
                                  kind: NodeKind.HogQLQuery,
                                  query: hogql`SELECT * FROM ${hogql.identifier(dataWarehouseSeriesTableNames[0])}`,
                              }
                            : undefined
                    }
                    schemaColumns={currentDataWarehouseSchemaColumns}
                    schemaColumnsLoading={hasDataWarehouseSeries && databaseLoading}
                />
            }
            visible={open}
            onClickOutside={() => setOpen(false)}
        >
            {children}
        </Popover>
    )
}
