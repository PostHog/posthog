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
    const {
        allEventNames,
        query,
        hasDataWarehouseSeries,
        hasOnlyDataWarehouseSeries,
        dataWarehouseSeriesTableNames,
        isTrends,
    } = useValues(insightVizDataLogic(insightProps))
    const { databaseLoading } = useValues(databaseTableListLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { includeSessions, taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    const { currentDataWarehouseSchemaColumns } = useValues(taxonomicBreakdownFilterLogic)
    const { addBreakdown, replaceBreakdown } = useActions(taxonomicBreakdownFilterLogic)

    // A SQL expression breakdown is parsed once per series, in that series' own scope, so one
    // expression can only resolve when every series reads the same warehouse table. Mixing an events
    // series in, or using two warehouse tables, fails on whichever series the expression does not
    // fit, and one failing series fails the whole insight.
    const allSeriesShareOneWarehouseTable = hasOnlyDataWarehouseSeries && dataWarehouseSeriesTableNames.length === 1

    let taxonomicGroupTypes: TaxonomicFilterGroupType[]
    if (hasDataWarehouseSeries) {
        taxonomicGroupTypes = [
            TaxonomicFilterGroupType.DataWarehouseProperties,
            // Funnels evaluate the expression on their events steps only, so a warehouse step gets
            // an empty breakdown value instead of a result.
            ...(isTrends && allSeriesShareOneWarehouseTable ? [TaxonomicFilterGroupType.HogQLExpression] : []),
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
                        allSeriesShareOneWarehouseTable
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
