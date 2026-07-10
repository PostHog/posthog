#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'

// Auto-replaces em dashes (— U+2014, ― U+2015) with a spaced hyphen on lines a
// commit actually adds. We ask people to "avoid em-dashes like the plague"
// (see AGENTS.md); this makes that automatic instead of something to review by
// hand. Invoked from lint-staged with the staged file paths appended as args.
//
// Scoped to *added* lines on purpose: the repo already contains thousands of
// pre-existing em dashes (many inside legitimate string data), so rewriting a
// whole file the moment someone touches it would bury real changes under an
// unrelated diff. We only ever rewrite what this commit introduces.

const EM_DASH = /[—―]/

// Collapse the horizontal whitespace around an em dash into a single spaced
// hyphen, while preserving the line's leading indentation.
function fixLine(line) {
    const [, indent, body] = line.match(/^([ \t]*)([\s\S]*)$/)
    return indent + body.replace(/[ \t]*[—―][ \t]*/g, ' - ')
}

// New-side line numbers that this staged change adds, parsed from the unified
// diff hunk headers (`@@ -a,b +c,d @@`). A fully new file reports every line.
function addedLineNumbers(file) {
    let diff
    try {
        diff = execFileSync('git', ['diff', '--cached', '-U0', '--', file], { encoding: 'utf8' })
    } catch {
        return null
    }
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

const fixed = []
for (const file of process.argv.slice(2)) {
    if (!fs.existsSync(file)) {
        continue
    }
    const added = addedLineNumbers(file)
    if (!added || added.size === 0) {
        continue
    }
    const original = fs.readFileSync(file, 'utf8')
    const lines = original.split('\n')
    let changed = false
    for (const n of added) {
        const idx = n - 1
        if (idx < 0 || idx >= lines.length || !EM_DASH.test(lines[idx])) {
            continue
        }
        const next = fixLine(lines[idx])
        if (next !== lines[idx]) {
            lines[idx] = next
            changed = true
        }
    }
    if (changed) {
        fs.writeFileSync(file, lines.join('\n'))
        fixed.push(file)
    }
}

if (fixed.length) {
    const yellow = (s) => `\x1b[33m${s}\x1b[0m`
    process.stderr.write(
        yellow(
            `\nReplaced em dashes with hyphens in ${fixed.length} file${fixed.length > 1 ? 's' : ''}:\n` +
                fixed.map((f) => `  ${f}`).join('\n') +
                `\n\n`
        )
    )
}

// Non-blocking: this fixes in place and lets lint-staged re-stage the result.
process.exit(0)
