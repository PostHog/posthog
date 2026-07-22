// Run with: node --test .github/scripts/label-pr-from-title.test.js
//
// Covers scope parsing and the scope -> labels mapping. The workflow runs under
// pull_request_target, so this unit test is the only pre-merge signal that the
// mapping logic is correct.

const test = require('node:test')
const assert = require('node:assert/strict')

const { parseScopes, parseType, docsLabelApplies, labelsForTitle, loadRules } = require('./label-pr-from-title')

// Mirrors the rule shape in .github/auto-assign-labels.json so the logic is
// exercised against the real structure without reading the file.
const RULES = [
    {
        scopes: ['flags', 'flag', 'feature-flags', 'feature-flag', 'feature_flags', 'feature_flag'],
        labels: ['feature/feature-flags', 'team/feature-flags'],
    },
    { scopes: ['cohort', 'cohorts'], labels: ['team/feature-flags', 'feature/cohorts'] },
]

const PARSE_SCOPES_CASES = [
    { title: 'feat(flags): add thing', expected: ['flags'], description: 'extracts a single scope' },
    { title: 'chore(cohorts)!: drop column', expected: ['cohorts'], description: 'handles the breaking-change bang' },
    {
        title: 'feat(Flags, Cohorts): x',
        expected: ['flags', 'cohorts'],
        description: 'lowercases and splits comma-separated scopes',
    },
    { title: 'chore: bump deps', expected: [], description: 'no scope -> empty' },
    { title: 'fix a bug (really)', expected: [], description: 'ignores parentheses that are not a CC scope' },
    { title: '', expected: [], description: 'empty title -> empty' },
]

test('parseScopes', async (t) => {
    for (const { title, expected, description } of PARSE_SCOPES_CASES) {
        await t.test(description, () => {
            assert.deepEqual(parseScopes(title), expected)
        })
    }
})

const LABELS_FOR_TITLE_CASES = [
    { title: 'feat(flags): x', expected: ['feature/feature-flags', 'team/feature-flags'], description: 'flags scope' },
    {
        title: 'fix(feature-flags): x',
        expected: ['feature/feature-flags', 'team/feature-flags'],
        description: 'feature-flags alias',
    },
    {
        title: 'feat(feature_flags): x',
        expected: ['feature/feature-flags', 'team/feature-flags'],
        description: 'underscore feature_flags alias',
    },
    { title: 'fix(cohort): x', expected: ['team/feature-flags', 'feature/cohorts'], description: 'cohort scope' },
    {
        title: 'feat(cohorts)!: x',
        expected: ['team/feature-flags', 'feature/cohorts'],
        description: 'cohorts alias with bang',
    },
    { title: 'feat(insights): x', expected: [], description: 'unrelated scope -> no labels' },
    { title: 'chore: bump', expected: [], description: 'no scope -> no labels' },
    {
        title: 'feat(flags,cohorts): x',
        expected: ['feature/feature-flags', 'team/feature-flags', 'feature/cohorts'],
        description: 'multi-scope de-dupes shared labels',
    },
]

test('labelsForTitle', async (t) => {
    for (const { title, expected, description } of LABELS_FOR_TITLE_CASES) {
        await t.test(description, () => {
            assert.deepEqual(labelsForTitle(title, RULES), expected)
        })
    }
})

const PARSE_TYPE_CASES = [
    { title: 'docs: add guide', expected: 'docs', description: 'type with no scope' },
    { title: 'docs(internal): x', expected: 'docs', description: 'type with scope' },
    { title: 'feat(flags): x', expected: 'feat', description: 'non-docs type' },
    { title: 'chore!: drop thing', expected: 'chore', description: 'breaking-change bang' },
    { title: 'update the docs please', expected: null, description: 'prose without a CC type -> null' },
    { title: '', expected: null, description: 'empty title -> null' },
]

test('parseType', async (t) => {
    for (const { title, expected, description } of PARSE_TYPE_CASES) {
        await t.test(description, () => {
            assert.equal(parseType(title), expected)
        })
    }
})

const DOCS_LABEL_CASES = [
    { title: 'docs: x', author: 'someuser', expected: true, description: 'docs type applies' },
    { title: 'docs(cdp): x', author: 'someuser', expected: true, description: 'docs type with scope applies' },
    { title: 'feat(flags): x', author: 'inkeep[bot]', expected: true, description: 'inkeep author applies on any title' },
    { title: 'feat(flags): x', author: 'someuser', expected: false, description: 'neither type nor author -> no docs label' },
    { title: 'chore: tidy up docs', author: 'someuser', expected: false, description: 'docs only in prose does not apply' },
]

test('docsLabelApplies', async (t) => {
    for (const { title, author, expected, description } of DOCS_LABEL_CASES) {
        await t.test(description, () => {
            assert.equal(docsLabelApplies(title, author), expected)
        })
    }
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

// Contributors write the flags scope several ways; these aliases were silently
// unlabeled until they were added to the config. Bind each to the shipped
// config (not just the RULES mirror) so a future edit that drops one regresses
// loudly here.
for (const scope of ['flag', 'feature-flag', 'feature_flags', 'feature_flag']) {
    test(`the shipped config maps the ${scope} scope to labels`, () => {
        assert.ok(labelsForTitle(`feat(${scope}): x`, loadRules()).length > 0, `${scope} scope maps to no labels`)
    })
}
