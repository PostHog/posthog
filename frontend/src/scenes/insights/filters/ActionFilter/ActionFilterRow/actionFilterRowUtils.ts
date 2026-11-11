import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { NodeKind } from '~/queries/schema/schema-general'

import { SeriesNode, WarehouseSeriesNodeKind, isActionsSeriesNode, isAllEventsSeriesNode } from '../seriesNode'

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
    switch (taxonomicFilterGroupType) {
        case TaxonomicFilterGroupType.Actions:
            return NodeKind.ActionsNode
        case TaxonomicFilterGroupType.DataWarehouse:
        case TaxonomicFilterGroupType.DataWarehouseSourceTables:
        case TaxonomicFilterGroupType.DataWarehouseMaterializedViews:
            return warehouseKind
        default:
            return NodeKind.EventsNode
    }
}
