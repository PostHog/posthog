// Run with: node --test .github/scripts/assign-reviewers.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const {
    CONFIG,
    isExcludedFile,
    classifyOwner,
    teamSlugToLabel,
    partitionExternalTeams,
    computeOwnerFootprints,
    isSubstantive,
    classifyOwners,
    buildReviewerComment,
    fileMatchesPattern,
} = require('./assign-reviewers')

const file = (filename, additions = 0, deletions = 0) => ({
    filename,
    additions,
    deletions,
})
// A resolver result entry: bare team slugs / @handles plus the deciding source.
const resolved = (owners, source) => ({ owners, source, status: 'active', slack: null })

// Asserts that actual contains all key/value pairs from partial (shallow per key, deep per value).
function assertMatchObject(actual, partial) {
    for (const [key, expected] of Object.entries(partial)) {
        assert.deepEqual(actual[key], expected)
    }
}

test('isExcludedFile: frontend/src/generated/core/api.ts -> true', () => {
    assert.equal(isExcludedFile('frontend/src/generated/core/api.ts'), true)
})
test('isExcludedFile: frontend/src/generated/core/api.schemas.ts -> true', () => {
    assert.equal(isExcludedFile('frontend/src/generated/core/api.schemas.ts'), true)
})
test('isExcludedFile: products/surveys/frontend/generated/api.zod.ts -> true', () => {
    assert.equal(isExcludedFile('products/surveys/frontend/generated/api.zod.ts'), true)
})
test('isExcludedFile: services/mcp/src/tools/generated/surveys.ts -> true', () => {
    assert.equal(isExcludedFile('services/mcp/src/tools/generated/surveys.ts'), true)
})
test('isExcludedFile: pnpm-lock.yaml -> true', () => {
    assert.equal(isExcludedFile('pnpm-lock.yaml'), true)
})
test('isExcludedFile: rust/Cargo.lock -> true', () => {
    assert.equal(isExcludedFile('rust/Cargo.lock'), true)
})
test('isExcludedFile: uv.lock -> true', () => {
    assert.equal(isExcludedFile('uv.lock'), true)
})
test('isExcludedFile: posthog/api/test/__snapshots__/test_survey.ambr -> true', () => {
    assert.equal(isExcludedFile('posthog/api/test/__snapshots__/test_survey.ambr'), true)
})
test('isExcludedFile: frontend/src/scenes/x/Component.test.tsx.snap -> true', () => {
    assert.equal(isExcludedFile('frontend/src/scenes/x/Component.test.tsx.snap'), true)
})
test('isExcludedFile: nodejs/src/ingestion/pipelines/ai/costs/providers/canonical-providers.ts -> true', () => {
    assert.equal(isExcludedFile('nodejs/src/ingestion/pipelines/ai/costs/providers/canonical-providers.ts'), true)
})
test('isExcludedFile: nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json -> true', () => {
    assert.equal(isExcludedFile('nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json'), true)
})
test('isExcludedFile: nodejs/src/ingestion/pipelines/ai/costs/providers/manual-providers.ts -> false', () => {
    assert.equal(isExcludedFile('nodejs/src/ingestion/pipelines/ai/costs/providers/manual-providers.ts'), false)
})
test('isExcludedFile: posthog/api/survey.py -> false', () => {
    assert.equal(isExcludedFile('posthog/api/survey.py'), false)
})
test('isExcludedFile: frontend/src/scenes/surveys/Survey.tsx -> false', () => {
    assert.equal(isExcludedFile('frontend/src/scenes/surveys/Survey.tsx'), false)
})

// a trailing slash is a directory boundary, not a name prefix
test('fileMatchesPattern: posthog/models/ai/utils.py vs posthog/models/ai/', () => {
    assert.equal(fileMatchesPattern('posthog/models/ai/utils.py', 'posthog/models/ai/'), true)
})
test('fileMatchesPattern: posthog/models/ai/sub/deep.py vs posthog/models/ai/', () => {
    assert.equal(fileMatchesPattern('posthog/models/ai/sub/deep.py', 'posthog/models/ai/'), true)
})
test('fileMatchesPattern: posthog/models/ai_events/event.py vs posthog/models/ai/', () => {
    assert.equal(fileMatchesPattern('posthog/models/ai_events/event.py', 'posthog/models/ai/'), false)
})
test('fileMatchesPattern: posthog/models/person/util.py vs posthog/models/person/', () => {
    assert.equal(fileMatchesPattern('posthog/models/person/util.py', 'posthog/models/person/'), true)
})
test('fileMatchesPattern: posthog/models/person_overrides/x.py vs posthog/models/person/', () => {
    assert.equal(fileMatchesPattern('posthog/models/person_overrides/x.py', 'posthog/models/person/'), false)
})
test('fileMatchesPattern: posthog/models/personal_api_key.py vs posthog/models/person/', () => {
    assert.equal(fileMatchesPattern('posthog/models/personal_api_key.py', 'posthog/models/person/'), false)
})
// /** is bounded to the directory, same as a trailing slash
test('fileMatchesPattern: posthog/models/ai/utils.py vs posthog/models/ai/**', () => {
    assert.equal(fileMatchesPattern('posthog/models/ai/utils.py', 'posthog/models/ai/**'), true)
})
test('fileMatchesPattern: posthog/models/ai_events/event.py vs posthog/models/ai/**', () => {
    assert.equal(fileMatchesPattern('posthog/models/ai_events/event.py', 'posthog/models/ai/**'), false)
})
// a single star stays within one path segment
test('fileMatchesPattern: posthog/dags/sessions.py vs posthog/dags/*.py', () => {
    assert.equal(fileMatchesPattern('posthog/dags/sessions.py', 'posthog/dags/*.py'), true)
})
test('fileMatchesPattern: posthog/dags/sub/sessions.py vs posthog/dags/*.py', () => {
    assert.equal(fileMatchesPattern('posthog/dags/sub/sessions.py', 'posthog/dags/*.py'), false)
})
// exact-file patterns match only that file
test('fileMatchesPattern: posthog/api/person.py vs posthog/api/person.py', () => {
    assert.equal(fileMatchesPattern('posthog/api/person.py', 'posthog/api/person.py'), true)
})
test('fileMatchesPattern: posthog/api/person_other.py vs posthog/api/person.py', () => {
    assert.equal(fileMatchesPattern('posthog/api/person_other.py', 'posthog/api/person.py'), false)
})

test('classifyOwner: @PostHog/team-surveys', () => {
    assert.deepEqual(classifyOwner('@PostHog/team-surveys'), {
        type: 'team',
        name: 'team-surveys',
        owner: '@PostHog/team-surveys',
    })
})
test('classifyOwner: @rafaeelaudibert', () => {
    assert.deepEqual(classifyOwner('@rafaeelaudibert'), {
        type: 'user',
        name: 'rafaeelaudibert',
        owner: '@rafaeelaudibert',
    })
})
test('classifyOwner: not-an-owner', () => {
    assert.equal(classifyOwner('not-an-owner'), null)
})

test('teamSlugToLabel: team-product-analytics -> team/product-analytics', () => {
    assert.equal(teamSlugToLabel('team-product-analytics'), 'team/product-analytics')
})
test('teamSlugToLabel: team-infra -> team/infra', () => {
    assert.equal(teamSlugToLabel('team-infra'), 'team/infra')
})
test('teamSlugToLabel: rafaeelaudibert -> null', () => {
    assert.equal(teamSlugToLabel('rafaeelaudibert'), null)
})
test('teamSlugToLabel: empty string -> null', () => {
    assert.equal(teamSlugToLabel(''), null)
})

test('partitionExternalTeams: labels product-analytics, still requests every other team', () => {
    const { toLabel, toRequest } = partitionExternalTeams([
        'team-product-analytics',
        'team-web-analytics',
        'team-infra',
    ])
    assert.deepEqual(toLabel, ['team-product-analytics'])
    assert.deepEqual(toRequest, ['team-web-analytics', 'team-infra'])
})

test('partitionExternalTeams: no product-analytics owner → nothing labelled, all requested', () => {
    const { toLabel, toRequest } = partitionExternalTeams(['team-web-analytics', 'team-infra'])
    assert.deepEqual(toLabel, [])
    assert.deepEqual(toRequest, ['team-web-analytics', 'team-infra'])
})

test('computeOwnerFootprints: ignores generated/excluded files and maps bare slugs to @PostHog handles', () => {
    const resolution = {
        'posthog/api/survey.py': resolved(['team-surveys'], 'products/surveys/product.yaml'),
        // Excluded before resolution, but assert it can't leak in even if present.
        'frontend/src/generated/core/api.ts': resolved(['team-devex'], 'owners.yaml'),
    }
    const files = [file('posthog/api/survey.py', 40, 10), file('frontend/src/generated/core/api.ts', 999, 999)]

    const footprints = computeOwnerFootprints(resolution, files)

    assert.equal(footprints.length, 1)
    assertMatchObject(footprints[0], {
        owner: '@PostHog/team-surveys',
        type: 'team',
        fileCount: 1,
        lines: 50,
        patterns: ['products/surveys/product.yaml'],
    })
})

test('computeOwnerFootprints: skips resolutions with generated/vendored status', () => {
    const resolution = {
        'posthog/api/survey.py': resolved(['team-surveys'], 'products/surveys/product.yaml'),
        'some/generated/tree/file.ts': { ...resolved(['team-devex'], 'some/generated/owners.yaml'), status: 'generated' },
        'vendor/lib/thing.js': { ...resolved(['team-devex'], 'vendor/owners.yaml'), status: 'vendored' },
    }
    const files = [
        file('posthog/api/survey.py', 40, 10),
        file('some/generated/tree/file.ts', 500, 500),
        file('vendor/lib/thing.js', 300, 0),
    ]

    const footprints = computeOwnerFootprints(resolution, files)

    assert.equal(footprints.length, 1)
    assertMatchObject(footprints[0], { owner: '@PostHog/team-surveys', fileCount: 1, lines: 50 })
})

test('computeOwnerFootprints: accumulates files and sources per owner, and requests @handle individuals as users', () => {
    const resolution = {
        'posthog/hogql/printer.py': resolved(['team-data-tools'], 'posthog/hogql/owners.yaml'),
        'posthog/hogql/parser.py': resolved(['team-data-tools', '@webjunkie'], 'posthog/hogql/owners.yaml'),
    }
    const files = [file('posthog/hogql/printer.py', 5, 3), file('posthog/hogql/parser.py', 2, 0)]

    const footprints = computeOwnerFootprints(resolution, files)

    const team = footprints.find((f) => f.owner === '@PostHog/team-data-tools')
    assertMatchObject(team, { type: 'team', fileCount: 2, lines: 10 })
    assert.deepEqual(team.patterns, ['posthog/hogql/owners.yaml'])

    const user = footprints.find((f) => f.owner === '@webjunkie')
    assertMatchObject(user, { type: 'user', name: 'webjunkie', fileCount: 1, lines: 2 })
})

for (const [footprint, expected] of [
    [{ lines: 50, fileCount: 1 }, true],
    [{ lines: 2, fileCount: 5 }, true],
    [{ lines: 2, fileCount: 1 }, false],
    [{ lines: CONFIG.substantiveLines, fileCount: 1 }, true],
    [{ lines: 0, fileCount: CONFIG.substantiveFiles }, true],
]) {
    test(`isSubstantive: ${JSON.stringify(footprint)} -> ${expected}`, () => {
        assert.equal(isSubstantive(footprint), expected)
    })
}

const fp = (owner, lines, fileCount = 1, type = 'team') => ({
    owner,
    type,
    name: owner.replace('@PostHog/', '').replace('@', ''),
    patterns: [owner],
    fileCount,
    lines,
})

test('classifyOwners: a single matched owner is always requested, even when tiny', () => {
    const { requested, demoted } = classifyOwners([fp('@PostHog/team-a', 1)])
    assert.equal(requested.length, 1)
    assert.equal(demoted.length, 0)
})

test('classifyOwners: demotes owners below the substantive bar but keeps substantive ones', () => {
    const { requested, demoted } = classifyOwners([fp('@PostHog/team-big', 120), fp('@PostHog/team-small', 2)])
    assert.deepEqual(
        requested.map((f) => f.owner),
        ['@PostHog/team-big']
    )
    assert.deepEqual(
        demoted.map((f) => f.owner),
        ['@PostHog/team-small']
    )
    assert.equal(demoted[0].reason, 'minor')
})

test('classifyOwners: promotes the largest owner when all are below the bar', () => {
    const { requested, demoted } = classifyOwners([
        fp('@PostHog/team-a', 1),
        fp('@PostHog/team-b', 4),
        fp('@PostHog/team-c', 2),
    ])
    assert.deepEqual(
        requested.map((f) => f.owner),
        ['@PostHog/team-b']
    )
    // The promoted owner is a clean request, not a demotion.
    assert.equal(requested[0].reason, undefined)
    assert.deepEqual(
        demoted.map((f) => f.owner),
        ['@PostHog/team-c', '@PostHog/team-a']
    )
})

test('classifyOwners: caps requested teams at maxTeamsRequested, demoting the smallest', () => {
    const footprints = Array.from({ length: CONFIG.maxTeamsRequested + 3 }, (_, i) =>
        fp(`@PostHog/team-${i}`, 50 + i)
    )
    const { requested, demoted } = classifyOwners(footprints)

    assert.equal(requested.filter((f) => f.type === 'team').length, CONFIG.maxTeamsRequested)
    assert.equal(demoted.length, 3)
    // Largest footprints are kept; the three smallest are demoted as capped.
    assert.equal(
        requested.some((f) => f.owner === `@PostHog/team-${footprints.length - 1}`),
        true
    )
    for (const expected of ['@PostHog/team-0', '@PostHog/team-1', '@PostHog/team-2']) {
        assert.ok(demoted.some((f) => f.owner === expected))
    }
    assert.equal(
        demoted.every((f) => f.reason === 'capped'),
        true
    )
})

test('classifyOwners: never caps explicit users even when teams overflow the cap', () => {
    // All substantive, so the cap (teams-only) is the only thing that can demote.
    const teams = Array.from({ length: CONFIG.maxTeamsRequested + 2 }, (_, i) =>
        fp(`@PostHog/team-${i}`, 50 + i)
    )
    const users = [fp('@user-a', 20, 1, 'user'), fp('@user-b', 20, 1, 'user')]
    const { requested, demoted } = classifyOwners([...teams, ...users])

    // Both users survive the cap...
    assert.deepEqual(
        requested
            .filter((f) => f.type === 'user')
            .map((f) => f.owner)
            .sort(),
        ['@user-a', '@user-b']
    )
    // ...while the smallest teams beyond the cap are demoted.
    assert.equal(requested.filter((f) => f.type === 'team').length, CONFIG.maxTeamsRequested)
    for (const expected of ['@PostHog/team-0', '@PostHog/team-1']) {
        assert.ok(demoted.some((f) => f.owner === expected))
    }
    assert.equal(
        demoted.every((f) => f.type === 'team'),
        true
    )
})

const requested = [
    {
        owner: '@PostHog/team-surveys',
        fileCount: 2,
        lines: 135,
        patterns: ['products/surveys/**'],
    },
]
const demoted = [
    {
        owner: '@PostHog/team-data-tools',
        fileCount: 1,
        lines: 2,
        patterns: ['posthog/hogql/**'],
        reason: 'minor',
    },
]

test('buildReviewerComment: returns null when no owner was dropped', () => {
    assert.equal(buildReviewerComment(requested, []), null)
    assert.equal(buildReviewerComment([...requested, requested[0]], []), null)
})

test('buildReviewerComment: lists each skipped owner as a bullet with its matched rule, not raw counts', () => {
    const body = buildReviewerComment(requested, demoted)
    assert.ok(body.includes(CONFIG.commentMarker))
    assert.ok(body.includes('- `@PostHog/team-data-tools` (`posthog/hogql/**`)'))
    assert.ok(body.includes('they only have minor changes here'))
    // No count theater: file/line numbers are internal-only, and no table.
    assert.ok(!/\d+ files/.test(body))
    assert.ok(!body.includes('| Lines |'))
})

test('buildReviewerComment: explains the reviewer cap when an owner was capped out', () => {
    const cappedDemoted = [{ ...demoted[0], reason: 'capped' }]
    const body = buildReviewerComment(requested, cappedDemoted)
    assert.ok(body.includes('the reviewer list was getting long'))
})

test('buildReviewerComment: truncates long pattern lists', () => {
    const manyDemoted = [
        {
            owner: '@PostHog/team-x',
            fileCount: 1,
            lines: 1,
            patterns: ['a/**', 'b/**', 'c/**', 'd/**', 'e/**'],
            reason: 'minor',
        },
    ]
    const body = buildReviewerComment(requested, manyDemoted)
    assert.ok(body.includes('(+3 more)'))
})
