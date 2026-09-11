import { RE2JS } from 're2js'

import { PathCleaningFilter } from '~/types'

/**
 * Expand a stored alias against one regex match, so the in-app preview agrees with the query that
 * actually runs.
 *
 * The alias is written in ClickHouse `replaceRegexpAll` (re2) syntax: `\0` is the whole match, `\1`
 * to `\9` are capture groups, `\\` is a literal backslash, and everything else is literal. That is
 * the only syntax users need to know, and the only one the backend understands.
 *
 * Expanding against the match here, rather than handing JavaScript a translated `$1`-style
 * replacement string, is what keeps three re2 rules JavaScript would otherwise break: `$` stays
 * literal, `\10` is group 1 followed by `0` rather than group 10, and a group the pattern never
 * filled substitutes as empty.
 */
export function expandAlias(alias: string, groups: (string | undefined)[]): string {
    let out = ''
    for (let i = 0; i < alias.length; i++) {
        const char = alias[i]
        if (char !== '\\') {
            out += char
            continue
        }
        const next = alias[i + 1]
        if (next === '\\') {
            out += '\\'
            i++
        } else if (next !== undefined && next >= '0' && next <= '9') {
            out += groups[Number(next)] ?? ''
            i++
        } else {
            out += '\\'
        }
    }
    return out
}

const RE2_INLINE_FLAGS = /^\(\?([imsUx]+)\)/

/**
 * Compile with the query engine's regex syntax, including scoped inline flags.
 *
 * Kept in step with `compileForPreview` in the MCP `update-path-cleaning` tool, so both previews of
 * the same rule set agree with each other as well as with the query.
 */
function compileForPreview(regex: string): RE2JS | null {
    if (!regex.replace(RE2_INLINE_FLAGS, '')) {
        return null
    }
    try {
        return RE2JS.compile(regex)
    } catch {
        return null
    }
}

/** Whether the preview can run this regex, so the editor refuses what it would not be able to show. */
export function isValidPathCleaningRegex(regex: string): boolean {
    return compileForPreview(regex) !== null
}

/**
 * Apply a single path-cleaning rule to a path, matching how the backend runs `replaceRegexpAll` per
 * rule. Invalid or empty regexes are skipped so a half-written rule can't blank out the preview.
 */
export function applyPathCleaningRule(path: string, filter: PathCleaningFilter): string {
    const pattern = filter.regex ? compileForPreview(filter.regex) : null
    if (!pattern) {
        return path
    }
    const alias = filter.alias ?? ''
    const matcher = pattern.matcher(path)
    let out = ''
    let end = 0
    while (matcher.find()) {
        const start = Number(matcher.start())
        const nextEnd = Number(matcher.end())
        const groups = Array.from({ length: pattern.groupCount() + 1 }, (_, index) => matcher.group(index) ?? undefined)
        out += path.slice(end, start) + expandAlias(alias, groups)
        end = nextEnd
    }
    return out + path.slice(end)
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
