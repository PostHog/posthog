import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, DataModelingNode, DataWarehouseSavedQuery } from '~/types'

import { WarehouseColumnAnnotationDescriptionSourceEnumApi } from '../generated/api.schemas'

export function canEditNodeDescription(
    node: DataModelingNode | null,
    savedQuery: DataWarehouseSavedQuery | null
): boolean {
    // A native table such as `events` has no warehouse table, so it has no annotation to edit.
    const isNativeTable = node?.type === 'table' && !node.warehouse_table_id
    return (
        node?.type !== 'metric' &&
        !isNativeTable &&
        userHasAccess(
            AccessControlResourceType.WarehouseObjects,
            AccessControlLevel.Editor,
            savedQuery?.user_access_level
        )
    )
}

export function isAiWrittenDescription(node: DataModelingNode | null): boolean {
    return (
        !!node?.description && node.description_source === WarehouseColumnAnnotationDescriptionSourceEnumApi.AiGenerated
    )
}
