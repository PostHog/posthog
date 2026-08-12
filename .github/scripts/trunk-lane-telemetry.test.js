// Run with: node --test .github/scripts/trunk-lane-telemetry.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { buildProperties } = require('./trunk-lane-telemetry')

// Stands in for the enumerated set a widening decision now uploads.
const UNIVERSE = ['fe:core', 'fe:product:alpha', 'prose', 'py:core', 'py:product:alpha']

// widening_reason is the field the dashboard acts on: a tripwire hit is a rule
// doing its job, while an unclassified path means a directory exists that no
// rule claims yet. Collapsing the two would hide the second behind the noise of
// the first, which is every workflow edit.
test('widening is attributed to the rule that caused it', () => {
    const cases = [
        [['.github/workflows/ci.yml'], UNIVERSE, 'tripwire'],
        [['terraform/main.tf'], UNIVERSE, 'unclassified_path'],
        [['products/alpha/frontend/Scene.tsx'], ['fe:product:alpha'], null],
        // The compute step widens and exits early when the merge base or diff
        // is unavailable, so the file list never reaches the script. Reading
        // that as unclassified_path would fake a missing-rule alert.
        [[], 'ALL', 'diff_unavailable'],
    ]
    for (const [files, targets, expected] of cases) {
        assert.equal(buildProperties(files, targets, UNIVERSE).widening_reason, expected, files[0])
    }
})

// A widened PR uploads the same array a genuinely repo-wide PR would, so only
// the universe separates them. Without it every widening reads as a PR that
// legitimately claimed every lane.
test('widening is recognized from the enumerated set, not just the sentinel', () => {
    const widened = buildProperties(['bin/start'], UNIVERSE, UNIVERSE)
    assert.equal(widened.is_all, true)
    assert.equal(widened.target_count, UNIVERSE.length)
    assert.deepEqual(widened.tripwire_files, ['bin/start'])

    const narrow = buildProperties(['products/alpha/frontend/Scene.tsx'], ['fe:product:alpha'], UNIVERSE)
    assert.equal(narrow.is_all, false)
})

// ALL is the string "ALL", not an array, so anything reading .length off it
// reports a target_count of 0 for both the widest and the narrowest outcome.
// It survives for the degraded cases, where the universe cannot be built.
test('the ALL sentinel still reports no targets but is flagged', () => {
    const props = buildProperties(['bin/start'], 'ALL', null)
    assert.equal(props.is_all, true)
    assert.equal(props.target_count, 0)
    assert.deepEqual(props.targets, [])
    assert.deepEqual(props.tripwire_files, ['bin/start'])
})

// Which domain widened a PR is the field that says whether a rule is pulling
// its weight, and it is not recoverable from the paths alone once the split
// exists.
test('tripwire domains are counted alongside the files', () => {
    const props = buildProperties(['.oxlintrc.json', 'mypy.ini', 'hogli.yaml'], UNIVERSE, UNIVERSE)
    assert.deepEqual(props.tripwire_domains, { javascript: 1, python: 1, universal: 1 })
})

test('file paths are summarized rather than sent', () => {
    const files = ['products/alpha/backend/api.py', 'products/beta/frontend/X.tsx', 'posthog/models/team.py']
    const props = buildProperties(files, ['py:core', 'fe:product:beta'])
    assert.deepEqual(props.changed_top_dirs, { products: 2, posthog: 1 })
    assert.deepEqual(props.changed_products, ['alpha', 'beta'])
    assert.equal(props.changed_file_count, 3)
    assert.deepEqual(props.target_domains, { py: 1, fe: 1 })
})
