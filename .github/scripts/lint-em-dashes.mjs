#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'

// Auto-replaces em dashes (— U+2014, ― U+2015) with a spaced hyphen on lines a
// commit actually adds. We ask people to "avoid em-dashes like the plague";
// this makes that automatic instead of something to review by hand. Invoked
// from lint-staged with the staged file paths appended as args.
//
// Scoped to *added* lines on purpose: the repo already contains thousands of
// pre-existing em dashes (many inside legitimate string data), so rewriting a
// whole file the moment someone touches it would bury real changes under an
// unrelated diff. We only ever rewrite what this commit introduces.
//
// The replacement is line-based, not language-aware: an em dash inside a string
// literal, regex, or fixture on an added line is rewritten too. That is
// intentional (the no-em-dash rule applies everywhere), but every rewrite is
// printed as a before/after pair so the change is never silent — if a rewrite
// is unwanted, that surfaces at commit time rather than in a later diff review.

const EM_DASH = /[—―]/

const yellow = (s) => `\x1b[33m${s}\x1b[0m`
const warn = (s) => process.stderr.write(yellow(s))

// Replace em dashes on a single line with a spaced hyphen. Leading indentation
// is preserved, and a space is only added on the side that has adjacent content
// — so a line-leading dash doesn't gain an indent-breaking space and a trailing
// dash doesn't leave trailing whitespace (meaningful in Markdown). Runs of
// consecutive dashes collapse to a single hyphen.
export function fixLine(line) {
    const [, indent, body] = line.match(/^([ \t]*)([\s\S]*)$/)
    const fixed = body.replace(/[ \t]*[—―]+[ \t]*/g, (match, offset) => {
        const spaceBefore = offset > 0 ? ' ' : ''
        const spaceAfter = offset + match.length < body.length ? ' ' : ''
        return `${spaceBefore}-${spaceAfter}`
    })
    return indent + fixed
}

// New-side line numbers a unified diff adds, parsed from its hunk headers
// (`@@ -a,b +c,d @@`). A fully new file reports every line; a pure deletion
// (`+c,0`) reports none.
export function parseAddedLineNumbers(diff) {
    const added = new Set()
    for (const line of diff.split('\n')) {
        const m = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/)
        if (!m) {
            continue
        }
        const start = Number(m[1])
        const count = m[2] === undefined ? 1 : Number(m[2])
        for (let i = 0; i < count; i++) {
            added.add(start + i)
        }
    }
    return added
}

// Line numbers this staged change adds for `file`. The git flags matter:
// --no-ext-diff and --no-color stop a user's difftastic or `color.diff=always`
// config from reshaping the output so the `@@` headers never match; the large
// maxBuffer stops a big staged diff from overflowing the default 1 MiB. Returns
// null (and warns) on error rather than silently skipping.
export function addedLineNumbers(file) {
    let diff
    try {
        diff = execFileSync('git', ['diff', '--no-ext-diff', '--no-color', '--cached', '-U0', '--', file], {
            encoding: 'utf8',
            maxBuffer: 64 * 1024 * 1024,
        })
    } catch (err) {
        warn(`\nem-dash fixer: could not read the staged diff for ${file}, skipping (${err.message})\n\n`)
        return null
    }
    return parseAddedLineNumbers(diff)
}

// Rewrite em dashes on the added lines of one file. Returns the list of
// rewrites made (empty if none), each with the 1-based line and its before/after.
function fixFile(file) {
    const added = addedLineNumbers(file)
    if (!added || added.size === 0) {
        return []
    }
    const buf = fs.readFileSync(file)
    const original = buf.toString('utf8')
    // Skip files that aren't losslessly UTF-8: re-encoding on write would turn
    // every invalid byte into U+FFFD and corrupt the whole file, well beyond
    // the added lines we mean to touch.
    if (!Buffer.from(original, 'utf8').equals(buf)) {
        warn(`\nem-dash fixer: ${file} is not valid UTF-8, skipping\n\n`)
        return []
    }
    const lines = original.split('\n')
    const rewrites = []
    for (const n of added) {
        const idx = n - 1
        if (idx < 0 || idx >= lines.length || !EM_DASH.test(lines[idx])) {
            continue
        }
        const next = fixLine(lines[idx])
        if (next !== lines[idx]) {
            rewrites.push({ line: n, before: lines[idx], after: next })
            lines[idx] = next
        }
    }
    if (rewrites.length) {
        fs.writeFileSync(file, lines.join('\n'))
    }
    return rewrites
}

function main(files) {
    const summary = []
    for (const file of files) {
        if (!fs.existsSync(file)) {
            continue
        }
        for (const r of fixFile(file)) {
            summary.push({ file, ...r })
        }
    }
    if (summary.length) {
        warn(
            `\nReplaced em dashes with hyphens on ${summary.length} line(s):\n` +
                summary
                    .map((r) => `  ${r.file}:${r.line}\n    - ${r.before.trim()}\n    + ${r.after.trim()}`)
                    .join('\n') +
                `\n\n`
        )
    }
}

// Run only when invoked directly, so the pure helpers above can be imported by
// the test without triggering the file rewrites.
if (process.argv[1] && fileURLToPath(import.meta.url) === fs.realpathSync(process.argv[1])) {
    main(process.argv.slice(2))
    // Non-blocking: this fixes in place and lets lint-staged re-stage the result.
    process.exit(0)
}
