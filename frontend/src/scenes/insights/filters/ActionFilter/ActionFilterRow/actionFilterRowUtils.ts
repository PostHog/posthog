import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { EntityType, EntityTypes } from '~/types'

import {
    SeriesNode,
    WarehouseSeriesNodeKind,
    isActionsSeriesNode,
    isAllEventsSeriesNode,
    seriesNodeKindForEntityType,
} from '../seriesNode'

export const getValue = (
    value: string | number | null | undefined,
    node: SeriesNode
): string | number | null | undefined => {
    if (isAllEventsSeriesNode(node)) {
        return 'All events'
    } else if (isActionsSeriesNode(node)) {
        return typeof value === 'string' ? parseInt(value) : value || undefined
    }
    return value === null ? null : value || undefined
}

/** The node kind a taxonomic group commits to, with the warehouse groups landing on the kind
 *  the caller asked the editor to create. */
export function taxonomicGroupTypeToSeriesNodeKind(
    taxonomicFilterGroupType: TaxonomicFilterGroupType,
    warehouseKind: WarehouseSeriesNodeKind = NodeKind.DataWarehouseNode
): SeriesNode['kind'] {
    return seriesNodeKindForEntityType(taxonomicFilterGroupTypeToEntityType(taxonomicFilterGroupType), warehouseKind)
}

const taxonomicFilterGroupTypeToEntityTypeMapping: Partial<Record<TaxonomicFilterGroupType, EntityTypes>> = {
    [TaxonomicFilterGroupType.Events]: EntityTypes.EVENTS,
    [TaxonomicFilterGroupType.Actions]: EntityTypes.ACTIONS,
    [TaxonomicFilterGroupType.DataWarehouse]: EntityTypes.DATA_WAREHOUSE,
    [TaxonomicFilterGroupType.DataWarehouseSourceTables]: EntityTypes.DATA_WAREHOUSE,
    [TaxonomicFilterGroupType.DataWarehouseMaterializedViews]: EntityTypes.DATA_WAREHOUSE,
}

export function taxonomicFilterGroupTypeToEntityType(
    taxonomicFilterGroupType: TaxonomicFilterGroupType
): EntityType | null {
    return taxonomicFilterGroupTypeToEntityTypeMapping[taxonomicFilterGroupType] || null
}
