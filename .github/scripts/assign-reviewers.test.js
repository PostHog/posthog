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
const rule = (pattern, ...owners) => ({ pattern, owners })

describe('assign-reviewers', () => {
    describe('isExcludedFile', () => {
        test.each([
            ['frontend/src/generated/core/api.ts', true],
            ['frontend/src/generated/core/api.schemas.ts', true],
            ['products/surveys/frontend/generated/api.zod.ts', true],
            ['services/mcp/src/tools/generated/surveys.ts', true],
            ['pnpm-lock.yaml', true],
            ['rust/Cargo.lock', true],
            ['uv.lock', true],
            ['posthog/api/test/__snapshots__/test_survey.ambr', true],
            ['frontend/src/scenes/x/Component.test.tsx.snap', true],
            ['nodejs/src/ingestion/pipelines/ai/costs/providers/canonical-providers.ts', true],
            ['nodejs/src/ingestion/pipelines/ai/costs/providers/llm-costs.json', true],
            ['nodejs/src/ingestion/pipelines/ai/costs/providers/manual-providers.ts', false],
            ['posthog/api/survey.py', false],
            ['frontend/src/scenes/surveys/Survey.tsx', false],
        ])('%s -> %s', (filename, expected) => {
            expect(isExcludedFile(filename)).toBe(expected)
        })
    })

    describe('fileMatchesPattern', () => {
        test.each([
            // a trailing slash is a directory boundary, not a name prefix
            ['posthog/models/ai/utils.py', 'posthog/models/ai/', true],
            ['posthog/models/ai/sub/deep.py', 'posthog/models/ai/', true],
            ['posthog/models/ai_events/event.py', 'posthog/models/ai/', false],
            ['posthog/models/person/util.py', 'posthog/models/person/', true],
            ['posthog/models/person_overrides/x.py', 'posthog/models/person/', false],
            ['posthog/models/personal_api_key.py', 'posthog/models/person/', false],
            // /** is bounded to the directory, same as a trailing slash
            ['posthog/models/ai/utils.py', 'posthog/models/ai/**', true],
            ['posthog/models/ai_events/event.py', 'posthog/models/ai/**', false],
            // a single star stays within one path segment
            ['posthog/dags/sessions.py', 'posthog/dags/*.py', true],
            ['posthog/dags/sub/sessions.py', 'posthog/dags/*.py', false],
            // exact-file patterns match only that file
            ['posthog/api/person.py', 'posthog/api/person.py', true],
            ['posthog/api/person_other.py', 'posthog/api/person.py', false],
        ])('%s vs %s', (filename, pattern, expected) => {
            expect(fileMatchesPattern(filename, pattern)).toBe(expected)
        })
    })

    describe('classifyOwner', () => {
        test.each([
            ['@PostHog/team-surveys', { type: 'team', name: 'team-surveys', owner: '@PostHog/team-surveys' }],
            ['@rafaeelaudibert', { type: 'user', name: 'rafaeelaudibert', owner: '@rafaeelaudibert' }],
            ['not-an-owner', null],
        ])('%s', (input, expected) => {
            expect(classifyOwner(input)).toEqual(expected)
        })
    })

    describe('teamSlugToLabel', () => {
        test.each([
            ['team-product-analytics', 'team/product-analytics'],
            ['team-infra', 'team/infra'],
            ['rafaeelaudibert', null],
            ['', null],
        ])('%s -> %s', (name, expected) => {
            expect(teamSlugToLabel(name)).toBe(expected)
        })
    })

    describe('partitionExternalTeams', () => {
        test('labels product-analytics, still requests every other team', () => {
            const { toLabel, toRequest } = partitionExternalTeams([
                'team-product-analytics',
                'team-web-analytics',
                'team-infra',
            ])
            expect(toLabel).toEqual(['team-product-analytics'])
            expect(toRequest).toEqual(['team-web-analytics', 'team-infra'])
        })

        test('no product-analytics owner → nothing labelled, all requested', () => {
            const { toLabel, toRequest } = partitionExternalTeams(['team-web-analytics', 'team-infra'])
            expect(toLabel).toEqual([])
            expect(toRequest).toEqual(['team-web-analytics', 'team-infra'])
        })
    })

    describe('computeOwnerFootprints', () => {
        test('ignores generated/excluded files when matching ownership', () => {
            const rules = [
                rule('posthog/api/survey.py', '@PostHog/team-surveys'),
                rule('frontend/src/generated/**', '@PostHog/team-devex'),
            ]
            const files = [file('posthog/api/survey.py', 40, 10), file('frontend/src/generated/core/api.ts', 999, 999)]

            const footprints = computeOwnerFootprints(rules, files)

            expect(footprints).toHaveLength(1)
            expect(footprints[0]).toMatchObject({
                owner: '@PostHog/team-surveys',
                type: 'team',
                fileCount: 1,
                lines: 50,
            })
        })

        test('dedupes a file owned via multiple rules and sums lines once', () => {
            const rules = [
                rule('posthog/hogql/**', '@PostHog/team-data-tools'),
                rule('posthog/hogql/printer.py', '@PostHog/team-data-tools'),
            ]
            const files = [file('posthog/hogql/printer.py', 5, 3)]

            const [footprint] = computeOwnerFootprints(rules, files)

            expect(footprint.fileCount).toBe(1)
            expect(footprint.lines).toBe(8)
            expect(footprint.patterns).toEqual(expect.arrayContaining(['posthog/hogql/**', 'posthog/hogql/printer.py']))
        })
    })

    describe('isSubstantive', () => {
        test.each([
            [{ lines: 50, fileCount: 1 }, true],
            [{ lines: 2, fileCount: 5 }, true],
            [{ lines: 2, fileCount: 1 }, false],
            [{ lines: CONFIG.substantiveLines, fileCount: 1 }, true],
            [{ lines: 0, fileCount: CONFIG.substantiveFiles }, true],
        ])('%o -> %s', (footprint, expected) => {
            expect(isSubstantive(footprint)).toBe(expected)
        })
    })

    describe('classifyOwners', () => {
        const fp = (owner, lines, fileCount = 1, type = 'team') => ({
            owner,
            type,
            name: owner.replace('@PostHog/', '').replace('@', ''),
            patterns: [owner],
            fileCount,
            lines,
        })

        test('a single matched owner is always requested, even when tiny', () => {
            const { requested, demoted } = classifyOwners([fp('@PostHog/team-a', 1)])
            expect(requested).toHaveLength(1)
            expect(demoted).toHaveLength(0)
        })

        test('demotes owners below the substantive bar but keeps substantive ones', () => {
            const { requested, demoted } = classifyOwners([fp('@PostHog/team-big', 120), fp('@PostHog/team-small', 2)])
            expect(requested.map((f) => f.owner)).toEqual(['@PostHog/team-big'])
            expect(demoted.map((f) => f.owner)).toEqual(['@PostHog/team-small'])
            expect(demoted[0].reason).toBe('minor')
        })

        test('promotes the largest owner when all are below the bar', () => {
            const { requested, demoted } = classifyOwners([
                fp('@PostHog/team-a', 1),
                fp('@PostHog/team-b', 4),
                fp('@PostHog/team-c', 2),
            ])
            expect(requested.map((f) => f.owner)).toEqual(['@PostHog/team-b'])
            // The promoted owner is a clean request, not a demotion.
            expect(requested[0].reason).toBeUndefined()
            expect(demoted.map((f) => f.owner)).toEqual(['@PostHog/team-c', '@PostHog/team-a'])
        })

        test('caps requested teams at maxTeamsRequested, demoting the smallest', () => {
            const footprints = Array.from({ length: CONFIG.maxTeamsRequested + 3 }, (_, i) =>
                fp(`@PostHog/team-${i}`, 50 + i)
            )
            const { requested, demoted } = classifyOwners(footprints)

            expect(requested.filter((f) => f.type === 'team')).toHaveLength(CONFIG.maxTeamsRequested)
            expect(demoted).toHaveLength(3)
            // Largest footprints are kept; the three smallest are demoted as capped.
            expect(requested.some((f) => f.owner === `@PostHog/team-${footprints.length - 1}`)).toBe(true)
            expect(demoted.map((f) => f.owner)).toEqual(
                expect.arrayContaining(['@PostHog/team-0', '@PostHog/team-1', '@PostHog/team-2'])
            )
            expect(demoted.every((f) => f.reason === 'capped')).toBe(true)
        })

        test('never caps explicit users even when teams overflow the cap', () => {
            // All substantive, so the cap (teams-only) is the only thing that can demote.
            const teams = Array.from({ length: CONFIG.maxTeamsRequested + 2 }, (_, i) =>
                fp(`@PostHog/team-${i}`, 50 + i)
            )
            const users = [fp('@user-a', 20, 1, 'user'), fp('@user-b', 20, 1, 'user')]
            const { requested, demoted } = classifyOwners([...teams, ...users])

            // Both users survive the cap...
            expect(
                requested
                    .filter((f) => f.type === 'user')
                    .map((f) => f.owner)
                    .sort()
            ).toEqual(['@user-a', '@user-b'])
            // ...while the smallest teams beyond the cap are demoted.
            expect(requested.filter((f) => f.type === 'team')).toHaveLength(CONFIG.maxTeamsRequested)
            expect(demoted.map((f) => f.owner)).toEqual(expect.arrayContaining(['@PostHog/team-0', '@PostHog/team-1']))
            expect(demoted.every((f) => f.type === 'team')).toBe(true)
        })
    })

    describe('buildReviewerComment', () => {
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

        test('returns null when no owner was dropped', () => {
            expect(buildReviewerComment(requested, [])).toBeNull()
            expect(buildReviewerComment([...requested, requested[0]], [])).toBeNull()
        })

        test('lists each skipped owner as a bullet with its matched rule, not raw counts', () => {
            const body = buildReviewerComment(requested, demoted)
            expect(body).toContain(CONFIG.commentMarker)
            expect(body).toContain('- `@PostHog/team-data-tools` (`posthog/hogql/**`)')
            expect(body).toContain('they only have minor changes here')
            // No count theater: file/line numbers are internal-only, and no table.
            expect(body).not.toMatch(/\d+ files/)
            expect(body).not.toContain('| Lines |')
        })

        test('explains the reviewer cap when an owner was capped out', () => {
            const cappedDemoted = [{ ...demoted[0], reason: 'capped' }]
            const body = buildReviewerComment(requested, cappedDemoted)
            expect(body).toContain('the reviewer list was getting long')
        })

        test('truncates long pattern lists', () => {
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
            expect(body).toContain('(+3 more)')
        })
    })
})
