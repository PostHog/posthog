// Run with: node --test .github/scripts/trunk-lane-telemetry.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { buildProperties } = require('./trunk-lane-telemetry')

// widening_reason is the field the dashboard acts on: a tripwire hit is a rule
// doing its job, while an unclassified path means a directory exists that no
// rule claims yet. Collapsing the two would hide the second behind the noise of
// the first, which is every workflow edit.
test('widening is attributed to the rule that caused it', () => {
    const cases = [
        [['.github/workflows/ci.yml'], 'ALL', 'tripwire'],
        [['terraform/main.tf'], 'ALL', 'unclassified_path'],
        [['products/alpha/frontend/Scene.tsx'], ['fe:product:alpha'], null],
        // The compute step widens and exits early when the merge base or diff
        // is unavailable, so the file list never reaches the script. Reading
        // that as unclassified_path would fake a missing-rule alert.
        [[], 'ALL', 'diff_unavailable'],
    ]
    for (const [files, targets, expected] of cases) {
        assert.equal(buildProperties(files, targets).widening_reason, expected, files[0])
    }
})

// ALL is the string "ALL", not an array, so anything reading .length off it
// reports a target_count of 0 for both the widest and the narrowest outcome.
test('an ALL change set reports no targets but is flagged', () => {
    const props = buildProperties(['bin/start'], 'ALL')
    assert.equal(props.is_all, true)
    assert.equal(props.target_count, 0)
    assert.deepEqual(props.targets, [])
    assert.deepEqual(props.tripwire_files, ['bin/start'])
})

test('file paths are summarized rather than sent', () => {
    const files = ['products/alpha/backend/api.py', 'products/beta/frontend/X.tsx', 'posthog/models/team.py']
    const props = buildProperties(files, ['py:core', 'fe:product:beta'])
    assert.deepEqual(props.changed_top_dirs, { products: 2, posthog: 1 })
    assert.deepEqual(props.changed_products, ['alpha', 'beta'])
    assert.equal(props.changed_file_count, 3)
    assert.deepEqual(props.target_domains, { py: 1, fe: 1 })
})
