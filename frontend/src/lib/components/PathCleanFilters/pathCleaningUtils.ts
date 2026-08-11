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
 * Compile a re2 pattern into a JS RegExp for the preview. re2 has no flags argument — it takes them
 * as a leading inline group like `(?i)`, which JavaScript rejects outright, so translate the ones JS
 * has an equivalent for. Everything else stays case-sensitive, matching re2's default.
 *
 * Kept in step with `compileForPreview` in the MCP `update-path-cleaning` tool, so both previews of
 * the same rule set agree with each other as well as with the query.
 */
function compileForPreview(regex: string): RegExp | null {
    const match = regex.match(RE2_INLINE_FLAGS)
    const inlineFlags = match ? match[1]! : ''
    const pattern = match ? regex.slice(match[0].length) : regex
    if (!pattern) {
        return null
    }
    // Ignore U and x — neither has a JS equivalent, and both are rare in path cleaning.
    const flags = 'g' + ['i', 'm', 's'].filter((flag) => inlineFlags.includes(flag)).join('')
    try {
        return new RegExp(pattern, flags)
    } catch {
        // A rule using re2-only syntax may not compile under JS RegExp. Skip it rather than throw.
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
    return path.replace(pattern, (match: string, ...rest: unknown[]): string => {
        // Replacer arguments run (match, p1…pN, offset, whole string, named groups?). A group the
        // pattern didn't fill arrives as undefined, so the first number is the offset and marks
        // where the capture values stop.
        const offsetIndex = rest.findIndex((arg) => typeof arg === 'number')
        const captures = (offsetIndex === -1 ? [] : rest.slice(0, offsetIndex)) as (string | undefined)[]
        return expandAlias(alias, [match, ...captures])
    })
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
