import type { HogFunctionFilters } from '~/cdp/types'

import type { LogRecord } from '../log-record-avro'
import { parseFilterGroup } from '../sampling/compile-rules'
import { type FilterGroupNode, matchFilterGroup } from '../sampling/filter-group-match'

type CompiledLogFilter = { kind: 'all' } | { kind: 'none' } | { kind: 'group'; group: FilterGroupNode }

const ALL: CompiledLogFilter = { kind: 'all' }
const NONE: CompiledLogFilter = { kind: 'none' }

// Function objects are reused across messages by the manager cache, so compile once per filters object.
const compiledCache = new WeakMap<HogFunctionFilters, CompiledLogFilter>()

function hasLeaf(node: unknown): boolean {
    if (!node || typeof node !== 'object') {
        return false
    }
    const maybe = node as { type?: unknown; values?: unknown }
    if (Array.isArray(maybe.values) && (maybe.type === 'AND' || maybe.type === 'OR')) {
        return maybe.values.some(hasLeaf)
    }
    return true
}

export function compileLogTransformationFilter(filters: HogFunctionFilters | null | undefined): CompiledLogFilter {
    if (!filters) {
        return ALL
    }
    const cached = compiledCache.get(filters)
    if (cached) {
        return cached
    }
    let compiled: CompiledLogFilter
    if (!hasLeaf(filters.filter_group)) {
        compiled = ALL
    } else {
        // Invalid groups match nothing: running a drop or redact on unintended records is worse than skipping.
        const group = parseFilterGroup(filters.filter_group)
        compiled = group ? { kind: 'group', group } : NONE
    }
    compiledCache.set(filters, compiled)
    return compiled
}

export function logTransformationFilterMatches(
    filters: HogFunctionFilters | null | undefined,
    record: LogRecord
): boolean {
    const compiled = compileLogTransformationFilter(filters)
    if (compiled.kind === 'all') {
        return true
    }
    if (compiled.kind === 'none') {
        return false
    }
    return matchFilterGroup(compiled.group, record)
}
