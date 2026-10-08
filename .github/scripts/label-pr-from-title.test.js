// Run with: node --test .github/scripts/label-pr-from-title.test.js
//
// Covers scope parsing and the scope -> labels mapping. The workflow runs under
// pull_request_target, so this unit test is the only pre-merge signal that the
// mapping logic is correct.

const test = require('node:test')
const assert = require('node:assert/strict')

const {
    parseScopes,
    parseType,
    docsLabelApplies,
    labelsForTitle,
    loadRules,
    isFlagsLowHangingFruitCandidate,
    isFlagsLowHangingFruit,
    flagsWithoutGeneratedFiles,
} = require('./label-pr-from-title')

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

// Desktop PRs rely on these scopes for the `feature/desktop` label; bind each
// to the shipped config so an edit that drops or mislabels one regresses
// loudly here. Asserts containment rather than the exact list so the rule can
// gain labels without breaking.
for (const scope of ['desktop', 'tasks', 'agent-proxy', 'canvas']) {
    test(`the shipped config maps the ${scope} scope to the desktop label`, () => {
        assert.ok(
            labelsForTitle(`feat(${scope}): x`, loadRules()).includes('feature/desktop'),
            `${scope} scope does not map to feature/desktop`
        )
    })
}

// ---------------------------------------------------------------------------
// Feature flags team only: the `review/low-hanging-fruit` label.
// ---------------------------------------------------------------------------

const FLAGS_LABELS = ['feature/feature-flags', 'team/feature-flags']

const FLAGS_CANDIDATE_CASES = [
    {
        author: 'posthog[bot]',
        labels: FLAGS_LABELS,
        expected: true,
        description: 'AI PR for the flags team is a candidate',
    },
    {
        author: 'someuser',
        labels: FLAGS_LABELS,
        expected: false,
        description: 'human PR for the flags team is not a candidate',
    },
    {
        author: 'posthog[bot]',
        labels: ['feature/desktop'],
        expected: false,
        description: 'AI PR for another team is not a candidate',
    },
]

test('isFlagsLowHangingFruitCandidate', async (t) => {
    for (const { author, labels, expected, description } of FLAGS_CANDIDATE_CASES) {
        await t.test(description, () => {
            assert.equal(isFlagsLowHangingFruitCandidate(author, labels), expected)
        })
    }
})

const file = (filename, additions, deletions = 0) => ({ filename, additions, deletions })
const generatedFiles = (count) =>
    Array.from({ length: count }, (_, i) => file(`frontend/src/generated/core/file${i}.ts`, 10))

const FLAGS_LOW_HANGING_FRUIT_CASES = [
    {
        files: [file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 20, 5)],
        expected: true,
        description: 'small single-file change',
    },
    {
        files: [file('a.py', 30, 5), file('b.py', 15)],
        expected: true,
        description: 'exactly at the line and file limits',
    },
    {
        files: [file('a.py', 30, 5), file('b.py', 16)],
        expected: false,
        description: 'one line over the line limit',
    },
    {
        files: [file('a.tsx', 1), file('b.tsx', 1), file('c.tsx', 1)],
        expected: false,
        description: 'one file over the file limit',
    },
    {
        files: [file('posthog/migrations/1234_add_column.py', 20)],
        expected: false,
        description: 'small Django migration',
    },
    {
        files: [file('rust/feature-flags/migrations/0001_init.sql', 10)],
        expected: false,
        description: 'small Rust migration',
    },
    {
        files: [file('.github/workflows/ci-rust.yml', 2, 2)],
        expected: false,
        description: 'small workflow change',
    },
    {
        files: [file('.github/actions/paths-filter/dist/index.js', 2, 2)],
        expected: false,
        description: 'small change to a generated file under .github/',
    },
    {
        files: [
            file('posthog/api/test/test_feature_flag.py', 400),
            file('frontend/src/scenes/feature-flags/featureFlagLogic.test.ts', 300),
            file('rust/feature-flags/src/flags/test_flag_matching.rs', 200),
            file('rust/feature-flags/tests/test_flags.rs', 100),
        ],
        expected: true,
        description: 'large tests-only change',
    },
    {
        files: [
            file('products/feature_flags/backend/local_evaluation.py', 30),
            file('posthog/utils.py', 20),
            file('products/feature_flags/backend/test/test_local_evaluation.py', 300),
            file('frontend/src/scenes/feature-flags/featureFlagLogic.test.ts', 100),
        ],
        expected: true,
        description: 'small source change with large tests',
    },
    {
        files: [file('frontend/src/scenes/feature-flags/FeatureFlagTestingTab.tsx', 200)],
        expected: false,
        description: 'large change to a component with "Testing" in its name',
    },
    {
        files: [
            file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 30),
            file('frontend/src/scenes/feature-flags/FeatureFlagSchedule.tsx', 30),
            file('frontend/src/scenes/feature-flags/FeatureFlag.scss', 20),
            file('products/feature_flags/frontend/FlagsTable.tsx', 10),
            file('frontend/src/scenes/feature-flags/FlagCard.tsx', 10),
        ],
        expected: true,
        description: 'UI tweak exactly at the line and file limits',
    },
    {
        files: [file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 50), file('a.scss', 1), file('b.css', 40)],
        expected: false,
        description: 'UI tweak with a style file outside the frontend directories',
    },
    {
        files: [
            file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 50),
            file('frontend/src/scenes/feature-flags/FeatureFlag.scss', 51),
        ],
        expected: false,
        description: 'UI tweak one line over the line limit',
    },
    {
        files: Array.from({ length: 6 }, (_, i) => file(`frontend/src/scenes/feature-flags/C${i}.tsx`, 1)),
        expected: false,
        description: 'UI tweak one file over the file limit',
    },
    {
        files: [
            file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 20),
            file('frontend/src/scenes/feature-flags/featureFlagLogic.ts', 20),
            file('frontend/src/scenes/feature-flags/flagsLogic.tsx', 20),
        ],
        expected: false,
        description: 'UI tweak that also changes kea logics',
    },
    {
        files: [...generatedFiles(98), file('a.tsx', 10)],
        expected: true,
        description: 'generated files below a full page do not count',
    },
    {
        files: [...generatedFiles(99), file('a.tsx', 10)],
        expected: false,
        description: 'a full page withholds the label, because later pages go unchecked',
    },
]

test('isFlagsLowHangingFruit', async (t) => {
    for (const { files, expected, description } of FLAGS_LOW_HANGING_FRUIT_CASES) {
        await t.test(description, () => {
            assert.equal(isFlagsLowHangingFruit(files), expected)
        })
    }
})

// Runs against the shipped .gitattributes, so it also fails if the generated
// API types stop being marked as `linguist-generated`.
test('flagsWithoutGeneratedFiles drops generated files and keeps hand-written ones', () => {
    const files = [
        file('frontend/src/generated/core/api.schemas.ts', 300),
        file('products/feature_flags/frontend/generated/api.ts', 120),
        file('products/desktop/packages/ui/src/router/routeTree.gen.ts', 40),
        file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 10),
    ]
    assert.deepEqual(flagsWithoutGeneratedFiles(files), [
        file('frontend/src/scenes/feature-flags/FeatureFlag.tsx', 10),
    ])
})
