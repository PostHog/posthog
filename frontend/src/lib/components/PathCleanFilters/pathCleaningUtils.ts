import { isValidRegexp } from 'lib/utils/regexp'

import { PathCleaningFilter } from '~/types'

/**
 * Translate a path-cleaning alias from ClickHouse `replaceRegexpAll` (re2) replacement syntax into a
 * JavaScript `String.replace` replacement string. The backend substitutes capture groups with re2's
 * `\1`–`\9` (and `\0` for the whole match); JS uses `$1`–`$9` and `$&`. A literal `$` must be escaped
 * to `$$` so JS doesn't read it as its own back-reference. Keeping the tester in step with re2 is the
 * whole point — otherwise a `\1` alias previews literally while the real query substitutes the group.
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
