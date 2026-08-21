// Run with: node --test .github/scripts/turbo-discover.test.js
//
// Pins turbo-discover's DJANGO_SEGMENTS table to the Django pytest invocations
// in ci-backend.yml. The table sizes the shards each segment gets, so a segment
// listing paths the workflow no longer runs (or missing ones it does) budgets
// wall time for a run that never happens, and the select-tests classify step
// routes selected files to a matrix leg that ignores them. Both workflow copies
// are read: the Depot mirror runs the same matrix and drifts on its own.
//
// Reads the workflow rather than a fixture on purpose — the workflow is the one
// side that can drift, and there is nothing else to compare the table against.

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const { DJANGO_SEGMENTS } = require('./turbo-discover')

const REPO_ROOT = path.join(__dirname, '..', '..')
const WORKFLOWS = ['.github/workflows/ci-backend.yml', '.depot/workflows/ci-backend.yml']

// pytest takes `./posthog/queries/` and `posthog` for the same directory, and
// --ignore drops the trailing slash. DJANGO_SEGMENTS stores prefixes, so every
// spelling has to land on the same one. File targets keep their extension.
function toPrefix(target) {
    const cleaned = target.replace(/^\.\//, '').replace(/\/$/, '')
    return cleaned.endsWith('.py') ? cleaned : `${cleaned}/`
}

function sorted(prefixes) {
    return [...new Set(prefixes)].sort()
}

function section(text, startMarker, endMarker) {
    const start = text.indexOf(startMarker)
    assert.notEqual(start, -1, `missing ${startMarker}`)
    const end = text.indexOf(endMarker, start)
    assert.notEqual(end, -1, `missing ${endMarker}`)
    return text.slice(start, end)
}

function matchAll(text, pattern) {
    return [...text.matchAll(pattern)].map((match) => match[1])
}

// The Core step runs both matrix legs: `full_targets` is reassigned per leg and
// the person-on-events leg adds its own ignores on top of the shared ones. The
// compat leg reads its targets from an env var, so it has no literal to pick up.
function parseCoreStep(text) {
    const step = section(text, 'full_targets="posthog ee/"', '--junitxml=junit-core.xml')
    const targets = matchAll(step, /full_targets="([^"]*)"/g).filter((value) => !value.startsWith('$'))
    assert.equal(targets.length, 2, 'expected a Core and a person-on-events full_targets assignment')
    const [core, poe] = targets.map((value) => value.trim().split(/\s+/))
    const poeIgnoreLine = step.match(/full_ignores\+=\(([^)]*)\)/)
    return {
        core,
        poe,
        ignores: matchAll(step.replace(/full_ignores\+=\([^)]*\)/g, ''), /--ignore=(\S+)/g),
        poeIgnores: poeIgnoreLine ? matchAll(poeIgnoreLine[1], /--ignore=(\S+)/g) : [],
    }
}

function parseTemporalTargets(text) {
    const invocation = text.match(/pytest [^\n]*junit_duration_report=call (posthog\/temporal[^\n]*?) -m /)
    assert.notEqual(invocation, null, 'missing the full Temporal pytest invocation')
    return invocation[1].split(/\s+/)
}

// Each classify arm is `pattern|pattern)` followed by its body up to `;;`. The
// body says which segment the arm feeds; an arm that appends nothing is a path
// the Core invocation ignores.
function parseClassifyArms(block) {
    const arms = { core: [], poe: [], temporal: [], ignored: [] }
    let patterns = null
    let body = ''
    for (const line of block.split('\n')) {
        const trimmed = line.trim()
        if (trimmed.startsWith('#')) {
            continue
        }
        if (patterns === null) {
            if (trimmed.endsWith(')')) {
                patterns = trimmed.slice(0, -1).split('|')
            }
            continue
        }
        if (trimmed !== ';;') {
            body += trimmed
            continue
        }
        const prefixes = patterns.map((pattern) => pattern.replace(/\*$/, ''))
        if (body.includes('temporal+=')) {
            arms.temporal.push(...prefixes)
        } else if (body.includes('poe+=')) {
            arms.poe.push(...prefixes)
        } else if (body.includes('core+=')) {
            arms.core.push(...prefixes)
        } else {
            arms.ignored.push(...prefixes)
        }
        patterns = null
        body = ''
    }
    assert.ok(arms.temporal.length && arms.poe.length && arms.core.length, 'classify arms not parsed')
    return arms
}

for (const workflow of WORKFLOWS) {
    const text = fs.readFileSync(path.join(REPO_ROOT, workflow), 'utf8')
    const core = parseCoreStep(text)
    const expected = {
        Core: { include: core.core, exclude: core.ignores },
        CorePOE: { include: core.poe, exclude: [...core.ignores, ...core.poeIgnores] },
        Temporal: { include: parseTemporalTargets(text), exclude: [] },
    }

    for (const [segment, paths] of Object.entries(expected)) {
        test(`${segment} segment matches the pytest targets in ${workflow}`, () => {
            assert.deepEqual(sorted(DJANGO_SEGMENTS[segment].include), sorted(paths.include.map(toPrefix)))
            assert.deepEqual(sorted(DJANGO_SEGMENTS[segment].exclude), sorted(paths.exclude.map(toPrefix)))
        })
    }

    // The classify step is the third copy of the partition: it routes each
    // selected file to a matrix leg, so an arm naming a path the pytest
    // invocation does not run sends tests to a leg that ignores them.
    test(`the select-tests classify arms match the segments in ${workflow}`, () => {
        const arms = parseClassifyArms(section(text, 'case "$f" in', 'esac'))

        assert.deepEqual(sorted(arms.temporal), sorted(DJANGO_SEGMENTS.Temporal.include))
        assert.deepEqual(sorted(arms.poe), sorted(DJANGO_SEGMENTS.CorePOE.include))
        assert.deepEqual(sorted(arms.core), sorted(DJANGO_SEGMENTS.Core.include))
        // The temporal arm comes first, so the paths it claims from inside the
        // Core scope are excluded from Core alongside the ignored arm's.
        const claimedFromCore = arms.temporal.filter((prefix) =>
            DJANGO_SEGMENTS.Core.include.some((include) => prefix.startsWith(include))
        )
        assert.deepEqual(sorted([...arms.ignored, ...claimedFromCore]), sorted(DJANGO_SEGMENTS.Core.exclude))
    })
}
