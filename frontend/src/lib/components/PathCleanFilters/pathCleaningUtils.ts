import { isValidRegexp } from 'lib/utils/regexp'

import { PathCleaningFilter } from '~/types'

/**
 * Adapt a stored alias to the replacement syntax of a JavaScript regex engine, purely so the
 * in-app preview agrees with the query that actually runs.
 *
 * The stored alias is written in ClickHouse `replaceRegexpAll` (re2) syntax, which addresses capture
 * groups as `\1` to `\9` and the whole match as `\0`. That is the only syntax users need to know, and
 * the only one the backend understands. No JavaScript engine speaks it: both native `String.replace`
 * and `re2js` address groups as `$1` and `$&` instead, so an unconverted `\1` previews as the literal
 * text `\1` (native) or `1` (re2js) rather than the captured value.
 *
 * The `$` escaping covers the reverse direction. ClickHouse emits `$` verbatim, so a literal `$1` in
 * an alias must be neutralized to `$$1` or JavaScript would substitute a group the user never asked
 * for, and `re2js` would throw when the group does not exist.
 */
export function aliasToJsReplacement(alias: string): string {
    let out = ''
    for (let i = 0; i < alias.length; i++) {
        const char = alias[i]
        if (char === '$') {
            out += '$$'
        } else if (char === '\\') {
            const next = alias[i + 1]
            if (next === '\\') {
                out += '\\'
                i++
            } else if (next >= '0' && next <= '9') {
                out += next === '0' ? '$&' : `$${next}`
                i++
            } else {
                out += '\\'
            }
        } else {
            out += char
        }
    }
    return out
}

/**
 * Apply a single path-cleaning rule to a path, matching how the backend runs `replaceRegexpAll` per
 * rule. Invalid or empty regexes are skipped so a half-written rule can't blank out the preview.
 */
export function applyPathCleaningRule(path: string, filter: PathCleaningFilter): string {
    if (!filter.regex || !isValidRegexp(filter.regex)) {
        return path
    }
    return path.replace(new RegExp(filter.regex, 'gi'), aliasToJsReplacement(filter.alias ?? ''))
}

/**
 * Chain every rule in order, each feeding the next — mirrors the sequential backend application.
 */
export function applyPathCleaning(path: string, filters: PathCleaningFilter[]): string {
    return filters.reduce((cleaned, filter) => applyPathCleaningRule(cleaned, filter), path)
}

/**
 * Ensures all filters have order values, using array position as fallback
 */
export function ensureFilterOrder(filters: PathCleaningFilter[]): PathCleaningFilter[] {
    return filters.map((filter, index) => ({
        ...filter,
        order: filter.order ?? index,
    }))
}

/**
 * Updates all filter order values to match their array position
 */
export function updateFilterOrder(filters: PathCleaningFilter[]): PathCleaningFilter[] {
    return filters.map((filter, index) => ({
        ...filter,
        order: index,
    }))
}
