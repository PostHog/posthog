import { DataWarehouseTableForInsight } from 'products/data_warehouse/frontend/types'

const ID_FIELD_CANDIDATES = ['id']
const DISTINCT_ID_FIELD_CANDIDATES = ['distinct_id', 'email', 'person_id', 'user_id', 'customer_id']
const AGGREGATION_TARGET_FIELD_CANDIDATES = ['person_id']
const AGGREGATION_TARGET_JOIN_CANDIDATES = [{ tableName: 'person_distinct_ids', fieldName: 'person_id' }]
const TIMESTAMP_FIELD_CANDIDATES = [
    'created',
    'created_at',
    'createdAt',
    'updated',
    'updated_at',
    'updatedAt',
    'timestamp',
    'date',
]

const normalizeFieldName = (fieldName: string): string => fieldName.toLowerCase()

function findFieldByNameCandidates(
    warehouseItem: DataWarehouseTableForInsight,
    candidates: string[]
): DataWarehouseTableForInsight['fields'][string] | undefined {
    const fields = Object.values(warehouseItem.fields)

    for (const candidate of candidates) {
        const normalizedCandidate = normalizeFieldName(candidate)
        const matchingField = fields.find((field) => normalizeFieldName(field.name) === normalizedCandidate)

        if (matchingField) {
            return matchingField
        }
    }

    return undefined
}

function findDateOrDatetimeField(
    warehouseItem: DataWarehouseTableForInsight
): DataWarehouseTableForInsight['fields'][string] | undefined {
    return Object.values(warehouseItem.fields).find((field) => field.type === 'datetime' || field.type === 'date')
}

function findJoinedFieldExpression(
    warehouseItem: DataWarehouseTableForInsight,
    tableName: string,
    fieldName: string
): string | undefined {
    const normalizedTableName = normalizeFieldName(tableName)
    const normalizedFieldName = normalizeFieldName(fieldName)

    const exactJoinField = Object.values(warehouseItem.fields).find(
        (field) =>
            normalizeFieldName(field.name) === normalizedTableName &&
            normalizeFieldName(field.table ?? '') === normalizedTableName &&
            field.fields?.some((candidate) => normalizeFieldName(candidate) === normalizedFieldName)
    )

    if (exactJoinField) {
        return `${exactJoinField.name}.${fieldName}`
    }

    const matchingJoinField = Object.values(warehouseItem.fields).find(
        (field) =>
            normalizeFieldName(field.table ?? '') === normalizedTableName &&
            field.fields?.some((candidate) => normalizeFieldName(candidate) === normalizedFieldName)
    )

    if (matchingJoinField) {
        return `${matchingJoinField.name}.${fieldName}`
    }

    return undefined
}

export function getDataWarehouseItemWithFieldDefaults(
    warehouseItem: DataWarehouseTableForInsight,
    selectedItemMeta?: Record<string, any> | null
): DataWarehouseTableForInsight {
    const isMatchingSelectedItem =
        selectedItemMeta &&
        (selectedItemMeta.table_name === warehouseItem.name ||
            selectedItemMeta.id === warehouseItem.name ||
            selectedItemMeta.name === warehouseItem.name)

    const warehouseItemWithFieldDefaults = isMatchingSelectedItem
        ? ({ ...warehouseItem, ...selectedItemMeta } as DataWarehouseTableForInsight)
        : { ...warehouseItem }

    if (warehouseItemWithFieldDefaults.id_field == null) {
        const idField = findFieldByNameCandidates(warehouseItemWithFieldDefaults, ID_FIELD_CANDIDATES)
        if (idField) {
            warehouseItemWithFieldDefaults.id_field = idField.name
        }
    }

    if (warehouseItemWithFieldDefaults.distinct_id_field == null) {
        const distinctIdField = findFieldByNameCandidates(warehouseItemWithFieldDefaults, DISTINCT_ID_FIELD_CANDIDATES)
        if (distinctIdField) {
            warehouseItemWithFieldDefaults.distinct_id_field = distinctIdField.name
        }
    }

    if (warehouseItemWithFieldDefaults.aggregation_target_field == null) {
        const aggregationTargetJoinField = AGGREGATION_TARGET_JOIN_CANDIDATES.map(({ tableName, fieldName }) =>
            findJoinedFieldExpression(warehouseItemWithFieldDefaults, tableName, fieldName)
        ).find((field): field is string => Boolean(field))
        const aggregationTargetField =
            aggregationTargetJoinField ??
            findFieldByNameCandidates(warehouseItemWithFieldDefaults, AGGREGATION_TARGET_FIELD_CANDIDATES)

        if (typeof aggregationTargetField === 'string') {
            warehouseItemWithFieldDefaults.aggregation_target_field = aggregationTargetField
        } else if (aggregationTargetField) {
            warehouseItemWithFieldDefaults.aggregation_target_field = aggregationTargetField.name
        }
    }

    if (warehouseItemWithFieldDefaults.timestamp_field == null) {
        const timestampNameField = findFieldByNameCandidates(warehouseItemWithFieldDefaults, TIMESTAMP_FIELD_CANDIDATES)
        const timestampTypeField = findDateOrDatetimeField(warehouseItemWithFieldDefaults)
        if (timestampNameField || timestampTypeField) {
            warehouseItemWithFieldDefaults.timestamp_field = timestampNameField?.name || timestampTypeField?.name
        }
    }

    return warehouseItemWithFieldDefaults
}
