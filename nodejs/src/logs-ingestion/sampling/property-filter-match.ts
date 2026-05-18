/**
 * Per-record property filter evaluator for log drop rules.
 *
 * Ported from `posthog/queries/base.py:match_property`. Keep semantics aligned
 * with the Python implementation; if you change one side, change the other.
 *
 * - `is_set` / `is_not_set` are the only operators that match a missing override.
 * - Date operators (is_date_before / after / exact) are intentionally omitted —
 *   the drop rule UI does not surface them and ingestion has no need.
 * - Unknown operators return false (no match → don't drop). Dropping is
 *   irreversible, so defaults are conservative.
 */

export type SupportedPropertyOperator =
    | 'exact'
    | 'is_not'
    | 'is_set'
    | 'is_not_set'
    | 'icontains'
    | 'not_icontains'
    | 'regex'
    | 'not_regex'
    | 'gt'
    | 'gte'
    | 'lt'
    | 'lte'
    | 'in'
    | 'not_in'

/** Leaf filter shape — mirrors the AnyPropertyFilter wire format. */
export interface PropertyFilterLeaf {
    key: string
    operator?: string
    value?: string | number | boolean | (string | number | boolean)[] | null
    type?: string
}

export function matchPropertyFilter(
    filter: PropertyFilterLeaf,
    overrideValue: string | number | boolean | null | undefined
): boolean {
    const operator = (filter.operator ?? 'exact') as SupportedPropertyOperator
    const value = filter.value

    if (operator === 'is_set') {
        return overrideValue !== undefined && overrideValue !== null && overrideValue !== ''
    }
    if (operator === 'is_not_set') {
        return overrideValue === undefined || overrideValue === null || overrideValue === ''
    }

    // For every remaining operator, a missing override never matches.
    if (overrideValue === undefined || overrideValue === null) {
        return false
    }

    if (operator === 'exact' || operator === 'in') {
        return matchExact(value, overrideValue)
    }
    if (operator === 'is_not' || operator === 'not_in') {
        return !matchExact(value, overrideValue)
    }

    if (operator === 'icontains') {
        return String(overrideValue).toLowerCase().includes(String(value).toLowerCase())
    }
    if (operator === 'not_icontains') {
        return !String(overrideValue).toLowerCase().includes(String(value).toLowerCase())
    }

    if (operator === 'regex' || operator === 'not_regex') {
        let rx: RegExp
        try {
            // Python source uses re.DOTALL | re.IGNORECASE — same as JS `s` + `i` flags.
            rx = new RegExp(String(value), 'is')
        } catch {
            return false
        }
        const matches = rx.test(String(overrideValue))
        return operator === 'regex' ? matches : !matches
    }

    if (operator === 'gt' || operator === 'gte' || operator === 'lt' || operator === 'lte') {
        return compareNumeric(value, overrideValue, operator)
    }

    return false
}

function matchExact(value: PropertyFilterLeaf['value'], overrideValue: string | number | boolean): boolean {
    if (isTruthyOrFalsyValue(value)) {
        const truthy = isTrueValue(value)
        return String(overrideValue).toLowerCase() === String(truthy).toLowerCase()
    }
    if (Array.isArray(value)) {
        const overrideStr = String(overrideValue).toLowerCase()
        return value.some((v) => String(v).toLowerCase() === overrideStr)
    }
    return String(value).toLowerCase() === String(overrideValue).toLowerCase()
}

// Mirrors `is_truthy_or_falsy_property_value` in posthog/queries/base.py.
function isTruthyOrFalsyValue(v: unknown): boolean {
    if (v === true || v === false) {
        return true
    }
    const truthyOrFalsy = ['true', 'True', 'false', 'False']
    if (typeof v === 'string') {
        return truthyOrFalsy.includes(v)
    }
    if (Array.isArray(v) && v.length === 1) {
        const inner = v[0]
        if (inner === true || inner === false) {
            return true
        }
        if (typeof inner === 'string') {
            return truthyOrFalsy.includes(inner)
        }
    }
    return false
}

function isTrueValue(v: unknown): boolean {
    if (v === true) {
        return true
    }
    if (typeof v === 'string') {
        return v === 'true' || v === 'True'
    }
    if (Array.isArray(v) && v.length === 1) {
        return isTrueValue(v[0])
    }
    return false
}

function compareNumeric(
    value: PropertyFilterLeaf['value'],
    overrideValue: string | number | boolean,
    operator: 'gt' | 'gte' | 'lt' | 'lte'
): boolean {
    // Mirrors Python: try numeric parse of `value`; if numeric and override parses to
    // a number, compare numerically. Otherwise fall back to lexicographic string compare.
    const parsedValue = typeof value === 'number' ? value : parseFloat(String(value))
    if (Number.isFinite(parsedValue)) {
        const overrideNum = typeof overrideValue === 'number' ? overrideValue : parseFloat(String(overrideValue))
        if (Number.isFinite(overrideNum)) {
            return cmp(overrideNum, parsedValue, operator)
        }
    }
    return cmp(String(overrideValue), String(value), operator)
}

function cmp<T extends number | string>(lhs: T, rhs: T, operator: 'gt' | 'gte' | 'lt' | 'lte'): boolean {
    switch (operator) {
        case 'gt':
            return lhs > rhs
        case 'gte':
            return lhs >= rhs
        case 'lt':
            return lhs < rhs
        case 'lte':
            return lhs <= rhs
    }
}
