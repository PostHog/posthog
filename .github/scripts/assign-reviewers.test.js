const {
    CONFIG,
    isExcludedFile,
    classifyOwner,
    computeOwnerFootprints,
    isSubstantive,
    classifyOwners,
    buildReviewerComment,
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
            ['posthog/api/survey.py', false],
            ['frontend/src/scenes/surveys/Survey.tsx', false],
        ])('%s -> %s', (filename, expected) => {
            expect(isExcludedFile(filename)).toBe(expected)
        })
    })

    describe('classifyOwner', () => {
        test('resolves teams, users, and rejects malformed', () => {
            expect(classifyOwner('@PostHog/team-surveys')).toEqual({
                type: 'team',
                name: 'team-surveys',
                owner: '@PostHog/team-surveys',
            })
            expect(classifyOwner('@rafaeelaudibert')).toEqual({
                type: 'user',
                name: 'rafaeelaudibert',
                owner: '@rafaeelaudibert',
            })
            expect(classifyOwner('not-an-owner')).toBeNull()
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
        })

        test('promotes the largest owner when all are below the bar', () => {
            const { requested, demoted } = classifyOwners([
                fp('@PostHog/team-a', 1),
                fp('@PostHog/team-b', 4),
                fp('@PostHog/team-c', 2),
            ])
            expect(requested.map((f) => f.owner)).toEqual(['@PostHog/team-b'])
            expect(demoted.map((f) => f.owner)).toEqual(['@PostHog/team-c', '@PostHog/team-a'])
        })

        test('caps requested teams at maxTeamsRequested, demoting the smallest', () => {
            const footprints = Array.from({ length: CONFIG.maxTeamsRequested + 3 }, (_, i) =>
                fp(`@PostHog/team-${i}`, 50 + i)
            )
            const { requested, demoted } = classifyOwners(footprints)

            expect(requested.filter((f) => f.type === 'team')).toHaveLength(CONFIG.maxTeamsRequested)
            expect(demoted).toHaveLength(3)
            // Largest footprints are kept; the three smallest are demoted.
            expect(requested.some((f) => f.owner === `@PostHog/team-${footprints.length - 1}`)).toBe(true)
            expect(demoted.map((f) => f.owner)).toEqual(
                expect.arrayContaining(['@PostHog/team-0', '@PostHog/team-1', '@PostHog/team-2'])
            )
        })

        test('never caps explicit users', () => {
            const users = Array.from({ length: CONFIG.maxTeamsRequested + 2 }, (_, i) =>
                fp(`@user-${i}`, 50, 1, 'user')
            )
            const { requested, demoted } = classifyOwners(users)
            expect(requested.filter((f) => f.type === 'user')).toHaveLength(users.length)
            expect(demoted).toHaveLength(0)
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
            },
        ]

        test('returns null with fewer than two owners', () => {
            expect(buildReviewerComment(requested, [])).toBeNull()
            expect(buildReviewerComment([], [])).toBeNull()
        })

        test('includes the marker, both sections, and code-wrapped owners', () => {
            const body = buildReviewerComment(requested, demoted)
            expect(body).toContain(CONFIG.commentMarker)
            expect(body).toContain('Requested for review')
            expect(body).toContain('not formally requested')
            // Owners are inline code so the comment does not re-notify.
            expect(body).toContain('`@PostHog/team-surveys`')
            expect(body).toContain('`@PostHog/team-data-tools`')
        })

        test('omits the minor-changes section when nothing is demoted', () => {
            const body = buildReviewerComment([...requested, demoted[0]], [])
            expect(body).not.toContain('not formally requested')
        })

        test('truncates long pattern lists', () => {
            const many = [
                {
                    owner: '@PostHog/team-x',
                    fileCount: 6,
                    lines: 60,
                    patterns: ['a/**', 'b/**', 'c/**', 'd/**', 'e/**'],
                },
                {
                    owner: '@PostHog/team-y',
                    fileCount: 1,
                    lines: 1,
                    patterns: ['z/**'],
                },
            ]
            const body = buildReviewerComment(many, [])
            expect(body).toContain('(+2 more)')
        })
    })
})
