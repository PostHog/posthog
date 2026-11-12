import { describe, expect, test } from 'bun:test'

import type {
    SkillAssetStatus,
    SkillReadRequest,
    SkillReadResult,
    SkillSearchResult,
    SkillsError,
    SkillsLibrary,
    SkillsLibraryOptions,
} from '@posthog/mcp/src/cli/library-types'

import { SKILL_COMMANDS } from '@/core/skill-commands'
import { runHog, type HogRun } from '@/testing'

const NETWORK: SkillAssetStatus[] = [
    {
        name: 'product-skills',
        url: 'https://example.com/skills.zip',
        origin: 'network',
        fetchedAt: '2026-01-01T00:00:00.000Z',
    },
    {
        name: 'context-mill',
        url: 'https://example.com/context-mill.zip',
        origin: 'network',
        fetchedAt: '2026-01-01T00:00:00.000Z',
    },
]

const SKILL_TEXT =
    'Skill: instrument-integration\n\nRead a file with `hog skills read instrument-integration --file <path>`.'

const READ: SkillReadResult = {
    text: SKILL_TEXT,
    reads: [{ source: 'posthog', skill: 'instrument-integration', path: 'SKILL.md', readKind: 'skill' }],
    assets: NETWORK,
}

interface FakeSkills {
    library: (options: SkillsLibraryOptions) => SkillsLibrary
    calls: readonly (SkillReadRequest | string)[]
    options: SkillsLibraryOptions[]
}

const FOUND: SkillSearchResult = {
    skills: [
        {
            name: 'session-replay',
            description: 'Watch how people use your app.\nMore detail.',
            matches: [
                { path: 'SKILL.md', line: 3, text: 'Record a session replay.' },
                { path: 'references/web.md', line: 8, text: '  Start session replay in the browser.' },
            ],
        },
    ],
    assets: NETWORK,
}

function fakeSkills(answer: SkillReadResult | SkillsError = READ, found = FOUND): FakeSkills {
    const calls: (SkillReadRequest | string)[] = []
    const options: SkillsLibraryOptions[] = []

    return {
        calls,
        options,
        library: (given) => {
            options.push(given)

            return {
                read: async (request) => {
                    calls.push(request)

                    return 'code' in answer ? { ok: false, error: answer } : { ok: true, value: answer }
                },
                search: async (keywords) => {
                    calls.push(keywords)

                    return { ok: true, value: found }
                },
                catalog: async () => ({
                    ok: true,
                    value: { skills: [], assets: NETWORK, release: { assets: NETWORK } },
                }),
                instrumentSkills: async () => ({ ok: true, value: { skills: [], assets: NETWORK } }),
                install: async () => ({ ok: false, error: { code: 'unknown_skill', message: 'Unknown skill' } }),
            }
        },
    }
}

function read(argv: string[], skills: FakeSkills, caller: 'agent' | 'person' = 'agent'): Promise<HogRun> {
    return runHog(['skills', 'read', ...argv], {
        ...(caller === 'person' ? { env: { NO_COLOR: '1' }, stdoutIsTTY: true } : { env: { CLAUDECODE: '1' } }),
        skills: skills.library,
    })
}

describe('hog skills read and search', () => {
    test.each<[string[], SkillReadRequest | string]>([
        [['read', 'funnels'], { skill: 'funnels' }],
        [['read', 'funnels', '--file', 'references/a.md'], { skill: 'funnels', file: 'references/a.md' }],
        [['read', 'funnels', '--lines', '1:20'], { skill: 'funnels', lines: '1:20' }],
        [
            ['read', 'funnels', '--file', 'references/a.md', '--lines', '1:20'],
            { skill: 'funnels', file: 'references/a.md', lines: '1:20' },
        ],
        [['search', 'node.js', 'next.js', 'tracing'], 'node.js next.js tracing'],
    ])('hog skills %j asks the library for %j', async (argv, request) => {
        const skills = fakeSkills()
        const result = await runHog(['skills', ...argv], { env: { CLAUDECODE: '1' }, skills: skills.library })
        expect(result.exitCode).toBe(0)
        expect(skills.calls).toEqual([request])
    })

    test.each([
        [['read', 'funnels', 'references/a.md']],
        [['read', 'funnels', 'posthog:retention']],
        [['read', '-s', 'replay']],
        [['read']],
        [['search']],
    ])('hog skills %j is refused before it loads the skills', async (argv) => {
        const skills = fakeSkills()

        const result = await runHog(['skills', ...argv], { env: { CLAUDECODE: '1' }, skills: skills.library })

        expect(result.exitCode).toBe(2)
        expect(skills.calls).toEqual([])
    })

    test('a person reads the skill text without logging in, and the skills cache in ~/.posthog/skills', async () => {
        const skills = fakeSkills()

        const result = await read(['posthog:instrument-integration'], skills, 'person')

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toBe(`${SKILL_TEXT}\n`)
        expect(result.requests).toEqual([])
        expect(skills.options).toEqual([
            {
                cacheDir: '/home/test/.posthog/skills',
                commands: SKILL_COMMANDS,
                fetch: expect.any(Function),
            },
        ])
    })

    test('a person sees the skill first, then that it came from the saved copy because the download failed', async () => {
        const cached: SkillAssetStatus[] = [
            { ...NETWORK[0]!, origin: 'cache', fetchedAt: '2026-01-01T09:30:00.000Z', failure: 'Unable to connect' },
            { ...NETWORK[1]!, origin: 'unavailable', fetchedAt: undefined, failure: 'HTTP 503' },
        ]
        const skills = fakeSkills({ ...READ, assets: cached })

        const result = await read(['posthog:instrument-integration'], skills, 'person')

        expect(result.stdout).toBe(
            [
                SKILL_TEXT,
                '',
                "hog couldn't download the PostHog product skills (Unable to connect). Using the copy saved on 2026-01-01 09:30 UTC.",
                "hog couldn't download the setup skills, such as posthog:instrument-integration (HTTP 503), and there's no saved copy.",
                '',
            ].join('\n')
        )
    })

    test('an agent gets the result as JSON, with the files read and where the skills came from', async () => {
        const result = await read(['posthog:instrument-integration'], fakeSkills())

        expect(result.json()).toEqual(READ)
    })

    test.each([
        [
            { code: 'offline', message: "Couldn't download the PostHog skills.", assets: NETWORK },
            'skills_offline',
            'Check your internet connection, then run the command again.',
            1,
        ],
        [
            { code: 'unknown_skill', message: 'Unknown skill: "nope".' },
            'unknown_skill',
            'Run `hog skills list` to see every skill.',
            1,
        ],
        [
            { code: 'unknown_file', message: 'Unknown file: "nope.md".' },
            'unknown_file',
            'Run `hog skills read <skill>` to see the files in the skill.',
            1,
        ],
        [
            { code: 'unavailable', message: 'This CLI serves PostHog skills only.' },
            'skills_unavailable',
            'Run `hog skills list` to see every skill.',
            1,
        ],
        [
            { code: 'usage', message: 'Invalid line range 1:999. instrument-integration/SKILL.md has 3 lines.' },
            'invalid_read_command',
            'Run `hog skills read --help` to see how to read a skill.',
            2,
        ],
    ] as const)('a %j failure is the HogError %s', async (error, code, hint, exitCode) => {
        const result = await read(['instrument-integration', '--file', 'nope.md'], fakeSkills(error))

        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, message: expect.stringContaining(error.message), hint })
    })

    test('--lines that are not a range fail before the skills load', async () => {
        const skills = fakeSkills()

        const result = await read(['funnels', '--lines', 'ten'], skills)

        expect(result.exitCode).toBe(2)
        expect(result.error().code).toBe('invalid_input')
        expect(skills.calls).toEqual([])
    })

    test('a person sees each skill found, its first matching lines, and how to read one', async () => {
        const result = await runHog(['skills', 'search', 'session', 'replay'], {
            env: { NO_COLOR: '1' },
            stdoutIsTTY: true,
            skills: fakeSkills().library,
        })

        expect(result.stdout).toBe(
            [
                'session-replay',
                '  Watch how people use your app.',
                '  SKILL.md:3: Record a session replay.',
                '  references/web.md:8: Start session replay in the browser.',
                '',
                '1 skill. Read one with hog skills read <skill>.',
                '',
            ].join('\n')
        )
    })

    test('an agent gets the skills found as JSON', async () => {
        const result = await runHog(['skills', 'search', 'session', 'replay'], {
            env: { CLAUDECODE: '1' },
            skills: fakeSkills().library,
        })

        expect(result.json()).toEqual(FOUND)
    })

    test('the usage event names the skills read and how, but not the search keywords', async () => {
        const result = await runHog(
            ['skills', 'read', 'instrument-integration', '--file', 'SKILL.md', '--lines', '1:2'],
            {
                env: { CLAUDECODE: '1' },
                telemetryToken: 'phc_test',
                skills: fakeSkills({
                    ...READ,
                    reads: [
                        {
                            source: 'posthog',
                            skill: 'instrument-integration',
                            path: 'SKILL.md',
                            readKind: 'file_lines',
                        },
                    ],
                }).library,
                respond: () => ({ status: 200, body: {} }),
            }
        )

        const batch = result.requests
            .filter((request) => request.url === 'https://us.i.posthog.com/batch/')
            .flatMap((request) => (request.body as { batch: unknown[] }).batch)
        expect(batch).toEqual([
            expect.objectContaining({
                event: 'posthog cli command run',
                properties: expect.objectContaining({
                    command_path: 'skills read',
                    options: ['file', 'lines'],
                    skills_read: ['posthog:instrument-integration'],
                    read_kinds: ['file_lines'],
                    skill_asset_origins: { 'product-skills': 'network', 'context-mill': 'network' },
                }),
            }),
        ])
        expect(JSON.stringify(batch)).not.toContain('SKILL.md')
    })

    test('the search event counts the skills found, but leaves the keywords out', async () => {
        const result = await runHog(['skills', 'search', 'secret-keywords'], {
            env: { CLAUDECODE: '1' },
            telemetryToken: 'phc_test',
            skills: fakeSkills().library,
            respond: () => ({ status: 200, body: {} }),
        })

        const batch = result.requests
            .filter((request) => request.url === 'https://us.i.posthog.com/batch/')
            .flatMap((request) => (request.body as { batch: unknown[] }).batch)
        expect(batch).toEqual([
            expect.objectContaining({
                properties: expect.objectContaining({ command_path: 'skills search', skills_found: 1 }),
            }),
        ])
        expect(JSON.stringify(batch)).not.toContain('secret-keywords')
    })
})
