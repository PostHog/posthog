// GitHub-faithful CODEOWNERS parser and matcher.
// From https://github.com/posthog/codeowners, a JS port of https://github.com/hmarr/codeowners
// Matching algorithm tracks hmarr/codeowners@b0f609d (pinned in testdata/.hmarr-sha).
// This is a standalone JS file with no dependencies, for easy vendoring.

'use strict'

/**
 * A single parsed CODEOWNERS rule.
 * @typedef {Object} CodeOwnerRule
 * @property {string} pattern The raw pattern, e.g. `docs/*` or `/build/logs/`.
 * @property {string[]} owners Owners as written, e.g. `@org/team`, `@user`, `a@b.com`.
 * @property {number} lineNumber 1-based line number in the source text.
 */

/**
 * @typedef {Object} CompiledMatcher
 * @property {(testPath: string) => boolean} test
 */

const SEP = '/'

/** @param {string} ch */
function quoteMeta(ch) {
    return /[.*+?^${}()|[\]\\]/.test(ch) ? '\\' + ch : ch
}

/**
 * Normalize a pattern into its GitHub-semantics path segments, applying the
 * leading-slash (root-anchor), slash-free (`**` prefix), and trailing-slash
 * (`**` suffix) rules. Shared by {@link patternToRegExp} and the runtime
 * matcher so the two cannot drift. Throws on the invalid patterns GitHub
 * rejects; `/` is handled by callers (it matches nothing) and not passed here.
 * @param {string} pattern
 * @returns {string[]}
 */
function patternToSegments(pattern) {
    if (pattern.includes('***')) {
        throw new Error('pattern cannot contain three consecutive asterisks')
    }
    if (pattern === '') {
        throw new Error('empty pattern')
    }

    let segs = pattern.split(SEP)

    if (segs[0] === '') {
        // Leading slash anchors to the repo root: drop the empty first segment.
        segs = segs.slice(1)
    } else if (segs.length === 1 || (segs.length === 2 && segs[1] === '')) {
        // A slash-free name (`foo`, `foo/`, `*.js`) matches at any depth, so it
        // behaves as if prefixed with `**/`.
        if (segs[0] !== '**') {
            segs = ['**', ...segs]
        }
    }

    if (segs.length > 1 && segs[segs.length - 1] === '') {
        // A trailing slash means "this directory and everything under it".
        segs[segs.length - 1] = '**'
    }

    // Collapse runs of consecutive `**` (from `a/**/**/b`, or a `foo/**/` whose
    // trailing slash became a second `**`) into one. They are semantically
    // identical to a single `**`, and two adjacent `**` would otherwise compile
    // to a degenerate, never-matching regex.
    const collapsed = []
    for (const seg of segs) {
        if (seg === '**' && collapsed[collapsed.length - 1] === '**') continue
        collapsed.push(seg)
    }
    return collapsed
}

/**
 * Translate a CODEOWNERS pattern into an anchored RegExp, mirroring GitHub's
 * segment semantics (and hmarr/codeowners' regex construction verbatim).
 *
 * This faithfully reproduces hmarr's `.+`-based `**` expansion, which is linear
 * under Go's RE2 but can backtrack super-linearly under JS's engine on adversarial
 * inputs (multiple non-terminal `**` segments against a deep non-matching path).
 * It is therefore kept for inspection, testing, and as the semantic reference;
 * the runtime matcher ({@link compilePattern}) uses an equivalent linear
 * segment-matcher instead. Most callers want {@link parse}.
 * @param {string} pattern
 * @returns {RegExp}
 */
function patternToRegExp(pattern) {
    if (pattern === '/') {
        // Matches the empty string only, i.e. nothing. (gitignore parity.)
        return /^$/
    }

    const segs = patternToSegments(pattern)
    const lastSegIndex = segs.length - 1
    let needSlash = false
    let re = '^'

    for (let i = 0; i < segs.length; i++) {
        const seg = segs[i]
        if (seg === '**') {
            if (i === 0 && i === lastSegIndex) {
                re += '.+'
            } else if (i === 0) {
                re += '(?:.+' + SEP + ')?'
                needSlash = false
            } else if (i === lastSegIndex) {
                re += SEP + '.*'
            } else {
                re += '(?:' + SEP + '.+)?'
                needSlash = true
            }
            continue
        }

        if (seg === '*') {
            if (needSlash) re += SEP
            re += '[^' + SEP + ']+'
            needSlash = true
            continue
        }

        // Literal segment, which may still contain `*`, `?`, or `\` escapes.
        if (needSlash) re += SEP
        let escape = false
        for (const ch of seg) {
            if (escape) {
                escape = false
                re += quoteMeta(ch)
            } else if (ch === '\\') {
                escape = true
            } else if (ch === '*') {
                re += '[^' + SEP + ']*'
            } else if (ch === '?') {
                re += '[^' + SEP + ']'
            } else {
                re += quoteMeta(ch)
            }
        }
        if (i === lastSegIndex) {
            // A literal final segment matches the path itself or anything under
            // it, so `/apps/github` owns `apps/github` and `apps/github/x`.
            re += '(?:' + SEP + '.*)?'
        }
        needSlash = true
    }

    re += '$'
    return new RegExp(re)
}

/**
 * Compile a single pattern segment (a literal that may contain `*`, `?`, or
 * `\` escapes) into an anchored RegExp matching exactly one path segment. The
 * segment never contains a `/`, so this regex cannot backtrack across segments.
 * @param {string} seg
 * @returns {RegExp}
 */
function segToRegExp(seg) {
    let re = '^'
    let escape = false
    for (const ch of seg) {
        if (escape) {
            escape = false
            re += quoteMeta(ch)
        } else if (ch === '\\') {
            escape = true
        } else if (ch === '*') {
            re += '[^' + SEP + ']*'
        } else if (ch === '?') {
            re += '[^' + SEP + ']'
        } else {
            re += quoteMeta(ch)
        }
    }
    re += '$'
    return new RegExp(re)
}

/**
 * One token of a compiled pattern: `**` (zero or more whole segments), `*`
 * (exactly one segment), or a literal segment with its single-segment test.
 * @typedef {Object} GlobToken
 * @property {'star' | 'one' | 'lit'} type
 * @property {(seg: string) => boolean} test Unused for `star`.
 */

/**
 * Match a tokenized pattern against a path's segments, with no backtracking
 * across segments: a bottom-up scan of `dp[ti][pi]` ("can tokens[ti..] match
 * segs[pi..]"), O(tokens × segments). This is the linear equivalent of the
 * {@link patternToRegExp} regex — it encodes the same `**`/`*`/literal rules,
 * including that a `**` tail (and `**` alone) requires at least one remaining
 * segment and that a literal final segment also owns its subtree — but cannot
 * blow up on adversarial multi-`**` patterns the way a backtracking regex does.
 * @param {GlobToken[]} tokens
 * @param {string[]} pathSegs
 * @returns {boolean}
 */
function globMatch(tokens, pathSegs) {
    const m = tokens.length
    const n = pathSegs.length
    // next holds dp[ti + 1][*]; seed it with dp[m][pi] = (no tokens left, so the
    // path must be exhausted).
    let next = new Array(n + 1)
    for (let pi = 0; pi <= n; pi++) next[pi] = pi === n
    for (let ti = m - 1; ti >= 0; ti--) {
        const tok = tokens[ti]
        const isLast = ti === m - 1
        const cur = new Array(n + 1).fill(false)
        if (tok.type === 'star') {
            if (isLast) {
                // A trailing `**` (`/.*`) consumes every remaining segment but
                // needs at least one; this also covers `**` as the whole pattern.
                for (let pi = 0; pi <= n; pi++) cur[pi] = n - pi >= 1
            } else {
                // `**` matches zero or more whole segments.
                cur[n] = next[n]
                for (let pi = n - 1; pi >= 0; pi--) cur[pi] = next[pi] || cur[pi + 1]
            }
        } else {
            // `*` and literal tokens each match exactly one segment.
            for (let pi = 0; pi < n; pi++) {
                if (!tok.test(pathSegs[pi])) continue
                // A literal final segment owns the matched path and its subtree,
                // so trailing segments are fine; everything else must line up.
                cur[pi] = isLast && tok.type === 'lit' ? true : next[pi + 1]
            }
        }
        next = cur
    }
    return next[0]
}

/**
 * Compile a wildcard pattern into a linear, backtrack-free matcher equivalent
 * to {@link patternToRegExp}. Throws on the same invalid patterns.
 * @param {string} pattern
 * @returns {CompiledMatcher}
 */
function compileGlob(pattern) {
    if (pattern === '/') {
        // Matches the empty string only, i.e. nothing. (gitignore parity.)
        return { test: (testPath) => testPath === '' }
    }
    /** @type {GlobToken[]} */
    const tokens = patternToSegments(pattern).map((seg) => {
        if (seg === '**') return { type: 'star', test: () => false }
        if (seg === '*') return { type: 'one', test: (s) => s.length >= 1 }
        const re = segToRegExp(seg)
        return { type: 'lit', test: (s) => re.test(s) }
    })
    return {
        test(testPath) {
            return globMatch(tokens, testPath === '' ? [] : testPath.split(SEP))
        },
    }
}

/**
 * Compile a pattern to a matcher, using a fast literal path for left-anchored
 * patterns with no wildcards (the common case in real CODEOWNERS files), and a
 * linear segment-matcher otherwise (see {@link globMatch}).
 * @param {string} pattern
 * @returns {CompiledMatcher}
 */
function compilePattern(pattern) {
    if (!/[*?\\]/.test(pattern) && pattern.startsWith('/')) {
        let prefix = pattern.slice(1)
        return {
            test(testPath) {
                if (prefix === '') return false
                if (prefix.endsWith(SEP)) return testPath.startsWith(prefix)
                if (testPath.length === prefix.length) return testPath === prefix
                if (testPath.length > prefix.length && testPath[prefix.length] === SEP) {
                    return testPath.slice(0, prefix.length) === prefix
                }
                return false
            },
        }
    }
    return compileGlob(pattern)
}

/** A matcher that owns nothing; used as the fallback for an invalid pattern. */
const NEVER_MATCH = { test: () => false }

/**
 * Like {@link compilePattern} but never throws: an invalid pattern (e.g. one
 * containing `***`) compiles to a never-match rule instead. Used for batch
 * compilation of a whole file, where one malformed line must not take the rest
 * of the rules down with it. Callers validating a single pattern want the
 * throwing {@link compilePattern} / {@link patternToRegExp} instead.
 * @param {string} pattern
 * @returns {CompiledMatcher}
 */
function compilePatternSafe(pattern) {
    try {
        return compilePattern(pattern)
    } catch {
        return NEVER_MATCH
    }
}

/**
 * Test whether a single CODEOWNERS pattern matches a repo-relative path. A
 * convenience for one-off checks and for validating patterns; most callers want
 * {@link parse} so that last-match-wins precedence is applied.
 * @param {string} pattern
 * @param {string} filePath A repo-relative path (a leading `/` is tolerated).
 * @returns {boolean}
 */
function pathMatchesPattern(pattern, filePath) {
    return compilePattern(pattern).test(normalizePath(filePath))
}

/** @param {string} filePath */
function normalizePath(filePath) {
    let p = filePath.replace(/\\/g, SEP)
    while (p.startsWith('./')) p = p.slice(2)
    while (p.startsWith(SEP)) p = p.slice(1)
    return p
}

class CodeOwners {
    /**
     * @param {CodeOwnerRule[]} rules
     */
    constructor(rules) {
        /** @type {CodeOwnerRule[]} */
        this.rules = rules
        // Compile defensively: a single malformed pattern becomes a never-match
        // rule rather than throwing, so one bad CODEOWNERS line cannot abort
        // owner resolution for every other rule (and every other PR).
        /** @type {CompiledMatcher[]} */
        this._matchers = rules.map((rule) => compilePatternSafe(rule.pattern))
    }

    /**
     * The last rule that matches `filePath`, or null if none. Last-match-wins is
     * GitHub's precedence rule.
     * @param {string} filePath A repo-relative path (a leading `/` is tolerated).
     * @returns {CodeOwnerRule | null}
     */
    matchingRule(filePath) {
        const p = normalizePath(filePath)
        for (let i = this.rules.length - 1; i >= 0; i--) {
            if (this._matchers[i].test(p)) return this.rules[i]
        }
        return null
    }

    /**
     * Owners of `filePath`, or an empty array if unowned.
     * @param {string} filePath
     * @returns {string[]}
     */
    ownersOf(filePath) {
        const rule = this.matchingRule(filePath)
        return rule ? rule.owners : []
    }
}

/**
 * Parse CODEOWNERS file contents into a {@link CodeOwners} matcher.
 * @param {string} text
 * @returns {CodeOwners}
 */
function parse(text) {
    /** @type {CodeOwnerRule[]} */
    const rules = []
    const lines = text.split(/\r?\n/)
    for (let i = 0; i < lines.length; i++) {
        const trimmed = lines[i].trim()
        // Only whole-line comments; GitHub does not support escaping a leading #.
        if (trimmed === '' || trimmed.startsWith('#')) continue
        const tokens = trimmed.split(/\s+/)
        rules.push({ pattern: tokens[0], owners: tokens.slice(1), lineNumber: i + 1 })
    }
    return new CodeOwners(rules)
}

module.exports = { parse, CodeOwners, patternToRegExp, pathMatchesPattern }
