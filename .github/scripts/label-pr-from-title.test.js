// Run with: node --test .github/scripts/label-pr-from-title.test.js
//
// Covers scope parsing and the scope -> labels mapping. The workflow runs under
// pull_request_target, so this unit test is the only pre-merge signal that the
// mapping logic is correct.

const test = require('node:test')
const assert = require('node:assert/strict')

const { parseScopes, labelsForTitle, loadRules } = require('./label-pr-from-title')

// Mirrors the rule shape in .github/auto-assign-labels.json so the logic is
// exercised against the real structure without reading the file.
const RULES = [
    { scopes: ['flags', 'feature-flags'], labels: ['feature/feature-flags', 'team/feature-flags'] },
    { scopes: ['cohort', 'cohorts'], labels: ['team/feature-flags', 'feature/cohorts'] },
]

test('parseScopes', async (t) => {
    await t.test('extracts a single scope', () => {
        assert.deepEqual(parseScopes('feat(flags): add thing'), ['flags'])
    })
    await t.test('handles the breaking-change bang', () => {
        assert.deepEqual(parseScopes('chore(cohorts)!: drop column'), ['cohorts'])
    })
    await t.test('lowercases and splits comma-separated scopes', () => {
        assert.deepEqual(parseScopes('feat(Flags, Cohorts): x'), ['flags', 'cohorts'])
    })
    await t.test('no scope -> empty', () => {
        assert.deepEqual(parseScopes('chore: bump deps'), [])
    })
    await t.test('ignores parentheses that are not a CC scope', () => {
        assert.deepEqual(parseScopes('fix a bug (really)'), [])
    })
    await t.test('empty title -> empty', () => {
        assert.deepEqual(parseScopes(''), [])
    })
})

test('labelsForTitle', async (t) => {
    await t.test('flags scope', () => {
        assert.deepEqual(labelsForTitle('feat(flags): x', RULES), ['feature/feature-flags', 'team/feature-flags'])
    })
    await t.test('feature-flags alias', () => {
        assert.deepEqual(labelsForTitle('fix(feature-flags): x', RULES), [
            'feature/feature-flags',
            'team/feature-flags',
        ])
    })
    await t.test('cohort scope', () => {
        assert.deepEqual(labelsForTitle('fix(cohort): x', RULES), ['team/feature-flags', 'feature/cohorts'])
    })
    await t.test('cohorts alias with bang', () => {
        assert.deepEqual(labelsForTitle('feat(cohorts)!: x', RULES), ['team/feature-flags', 'feature/cohorts'])
    })
    await t.test('unrelated scope -> no labels', () => {
        assert.deepEqual(labelsForTitle('feat(insights): x', RULES), [])
    })
    await t.test('no scope -> no labels', () => {
        assert.deepEqual(labelsForTitle('chore: bump', RULES), [])
    })
    await t.test('multi-scope de-dupes shared labels', () => {
        assert.deepEqual(labelsForTitle('feat(flags,cohorts): x', RULES), [
            'feature/feature-flags',
            'team/feature-flags',
            'feature/cohorts',
        ])
    })
})

// Catches a malformed or empty .github/auto-assign-labels.json in this PR's
// ci-scripts run, rather than letting it silently disable labeling on master.
test('the shipped config loads into well-formed rules', () => {
    const rules = loadRules()
    assert.ok(rules.length > 0, 'config has no rules')
    for (const rule of rules) {
        assert.ok(Array.isArray(rule.scopes) && rule.scopes.length > 0, 'rule missing scopes')
        assert.ok(Array.isArray(rule.labels) && rule.labels.length > 0, 'rule missing labels')
    }
})

// The logic tests above run against the local RULES mirror, so a config-only
// edit (the supported workflow) that deletes or renames the `flags` rule would
// ship green. Bind one known scope to the real config to catch that. Asserts
// non-empty rather than exact labels so an intentional label rename doesn't fail.
test('the shipped config still maps the flags scope to labels', () => {
    assert.ok(labelsForTitle('feat(flags): x', loadRules()).length > 0, 'flags scope maps to no labels')
})
