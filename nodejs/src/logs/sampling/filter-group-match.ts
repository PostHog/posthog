/**
 * Recursive evaluator for the UniversalFiltersGroup shape (the matcher the
 * drop-rules UI writes into `config.filter_group`).
 *
 * Group nodes have `{type: 'AND' | 'OR', values: [...]}`; leaves are
 * PropertyFilters (see property-filter-match.ts). Nested groups are supported.
 *
 * SAFETY: empty groups return false (no match → don't drop). Dropping is
 * irreversible, so when the filter is vacuous we let the line through.
 * The drop-rule form validates non-empty before submit; this is defense in
 * depth at the worker boundary.
 */
import type { LogRecord } from '~/logs/log-record-avro'

import { type PropertyFilterLeaf, matchPropertyFilter } from './property-filter-match'

export type FilterGroupNode = {
    type: 'AND' | 'OR'
    values: Array<PropertyFilterLeaf | FilterGroupNode>
}

const PROPERTY_FILTER_TYPE_LOG = 'log'
const PROPERTY_FILTER_TYPE_LOG_ATTRIBUTE = 'log_attribute'
const PROPERTY_FILTER_TYPE_LOG_RESOURCE_ATTRIBUTE = 'log_resource_attribute'

/**
 * Hard ceiling on filter-group nesting depth. The drop-rules UI surfaces at
 * most 2 levels in practice; we leave generous headroom for hand-edited or
 * future shapes. Beyond this we return false (no match → don't drop) so a
 * pathological deeply-nested rule cannot blow the Node stack on every record.
 * Pydantic validation in `sampling_api.py` enforces the same bound at write
 * time; both sides exist so existing rows that predate the validator still
 * degrade safely.
 */
export const MAX_FILTER_GROUP_DEPTH = 16

export function matchFilterGroup(group: FilterGroupNode, record: LogRecord, depth: number = 0): boolean {
    if (depth >= MAX_FILTER_GROUP_DEPTH) {
        return false
    }
    if (!group.values || group.values.length === 0) {
        return false
    }
    if (group.type === 'OR') {
        return group.values.some((child) => matchOne(child, record, depth + 1))
    }
    // Default to AND for any unrecognised operator.
    return group.values.every((child) => matchOne(child, record, depth + 1))
}

function matchOne(node: PropertyFilterLeaf | FilterGroupNode, record: LogRecord, depth: number): boolean {
    if (isGroupNode(node)) {
        return matchFilterGroup(node, record, depth)
    }
    return matchPropertyFilter(node, lookupRecordValue(node, record))
}

function isGroupNode(node: PropertyFilterLeaf | FilterGroupNode): node is FilterGroupNode {
    const maybe = node as FilterGroupNode
    return Array.isArray(maybe.values) && (maybe.type === 'AND' || maybe.type === 'OR')
}

/**
 * Map a property filter's `key` (and `type` when present) to the corresponding
 * value on the LogRecord. First-class columns (service_name, severity_text,
 * body) win over the attribute maps; otherwise the declared filter type picks
 * `attributes` vs `resource_attributes`; missing type falls back to attribute
 * map then resource map.
 */
function lookupRecordValue(filter: PropertyFilterLeaf, record: LogRecord): string | null | undefined {
    const key = filter.key

    // First-class columns win when populated; otherwise fall back to the
    // matching attribute map. Ingestion denormalises service.name + severity_text
    // onto first-class fields, but partial decodes / older records may have only
    // the resource/log attribute present.
    if (key === 'service_name' || key === 'service.name') {
        // Always fall back via the OTel-canonical dotted key — `service_name`
        // (underscore) is only the in-memory Avro field name, never an OTel
        // resource attribute. Looking up `resource_attributes['service_name']`
        // would silently miss real data.
        return record.service_name ?? record.resource_attributes?.['service.name']
    }
    if (key === 'severity_text' || key === 'level' || key === 'severity_level') {
        // First-class column wins. Otherwise fall back to attribute storage,
        // trying the SDK convention (`level` — Winston/Pino/Bunyan/log4j2) first
        // and the OTel-style `severity_text` second. The fallback chain does not
        // depend on which key the filter used, so `level: info` and
        // `severity_text: info` always resolve to the same value for the same
        // record (otherwise we'd silently disagree when only one of the two
        // attribute names is populated). `severity_level` is the logs UI / HogQL
        // alias and the key the drop-rule builder writes; without this branch it
        // falls through to the `type: 'log'` body fallback and never matches.
        return record.severity_text ?? record.attributes?.['level'] ?? record.attributes?.['severity_text']
    }
    if (key === 'message' || filter.type === PROPERTY_FILTER_TYPE_LOG) {
        return record.body ?? undefined
    }

    if (filter.type === PROPERTY_FILTER_TYPE_LOG_RESOURCE_ATTRIBUTE) {
        return record.resource_attributes?.[key]
    }
    if (filter.type === PROPERTY_FILTER_TYPE_LOG_ATTRIBUTE) {
        return record.attributes?.[key]
    }
    return record.attributes?.[key] ?? record.resource_attributes?.[key]
}
