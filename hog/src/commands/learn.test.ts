import { describe, expect, test } from 'bun:test'

import type {
    LearnResult,
    SkillAssetStatus,
    SkillsError,
    SkillsLibrary,
    SkillsLibraryOptions,
} from '@posthog/mcp/src/cli/library-types'

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
    'Skill: posthog:instrument-integration\n\nRead a file with `hog learn posthog:instrument-integration <path>`.'

const READ: LearnResult = {
    output: {
        kind: 'text',
        text: SKILL_TEXT,
    },
    reads: [{ source: 'posthog', skill: 'instrument-integration', path: 'SKILL.md', readKind: 'skill' }],
    assets: NETWORK,
}

interface FakeSkills {
    library: (options: SkillsLibraryOptions) => SkillsLibrary
    calls: readonly string[][]
    options: SkillsLibraryOptions[]
}

function fakeSkills(answer: LearnResult | SkillsError = READ): FakeSkills {
    const calls: string[][] = []
    const options: SkillsLibraryOptions[] = []
    return {
        calls,
        options,
        library: (given) => {
            options.push(given)
            return {
                learn: async (words) => {
                    calls.push([...words])
                    return 'code' in answer ? { ok: false, error: answer } : { ok: true, value: answer }
                },
                installable: async () => ({ ok: true, value: { skills: [], assets: NETWORK } }),
                install: async () => ({ ok: false, error: { code: 'unknown_skill', message: 'Unknown skill' } }),
            }
        },
    }
}

function learn(argv: string[], skills: FakeSkills, caller: 'agent' | 'person' = 'agent'): Promise<HogRun> {
    return runHog(['learn', ...argv], {
        ...(caller === 'person' ? { env: { NO_COLOR: '1' }, stdoutIsTTY: true } : { env: { CLAUDECODE: '1' } }),
        skills: skills.library,
    })
}

describe('hog learn', () => {
    test.each([
        [[], []],
        [['skills'], ['skills']],
        [
            ['-s', 'session replay'],
            ['-s', 'session replay'],
        ],
        [
            ['-s', 'session', 'replay'],
            ['-s', 'session', 'replay'],
        ],
        [
            ['-d', 'posthog:funnels', 'posthog:retention'],
            ['-d', 'posthog:funnels', 'posthog:retention'],
        ],
        [
            ['posthog:funnels', 'SKILL.md', '-s', 'conversion'],
            ['posthog:funnels', 'SKILL.md', '-s', 'conversion'],
        ],
        [
            ['posthog:funnels', 'SKILL.md', '--lines', '1:20'],
            ['posthog:funnels', 'SKILL.md', '--lines', '1:20'],
        ],
        [
            ['posthog:funnels', 'a.md', 'b.md'],
            ['posthog:funnels', 'a.md', 'b.md'],
        ],
        [
            ['-s', 'conversion', 'posthog:funnels', 'SKILL.md'],
            ['posthog:funnels', 'SKILL.md', '-s', 'conversion'],
        ],
        [
            ['posthog:funnels', 'SKILL.md', '-s', 'conversion', 'rate'],
            ['posthog:funnels', 'SKILL.md', '-s', 'conversion', 'rate'],
        ],
    ])('hog learn %j runs learn %j', async (argv, words) => {
        const skills = fakeSkills()
        const result = await learn(argv, skills)
        expect(result.exitCode).toBe(0)
        expect(skills.calls).toEqual([words])
    })

    test('a person reads the skill text without logging in, and the skills cache in ~/.posthog/skills', async () => {
        const skills = fakeSkills()

        const result = await learn(['posthog:instrument-integration'], skills, 'person')

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toBe(`${SKILL_TEXT}\n`)
        expect(result.requests).toEqual([])
        expect(skills.options).toEqual([
            { cacheDir: '/home/test/.posthog/skills', learnCommand: 'hog learn', fetch: expect.any(Function) },
        ])
    })

    test('a person sees that the skills came from the saved copy when the download failed', async () => {
        const cached: SkillAssetStatus[] = [
            { ...NETWORK[0]!, origin: 'cache', fetchedAt: '2026-01-01T09:30:00.000Z', failure: 'Unable to connect' },
            { ...NETWORK[1]!, origin: 'unavailable', fetchedAt: undefined, failure: 'HTTP 503' },
        ]
        const skills = fakeSkills({ ...READ, assets: cached })

        const result = await learn(['posthog:instrument-integration'], skills, 'person')

        expect(result.stdout.split('\n').slice(0, 2)).toEqual([
            "hog couldn't download the PostHog product skills (Unable to connect), so these come from the copy saved on 2026-01-01 09:30 UTC.",
            "hog couldn't download the setup skills, such as posthog:instrument-integration (HTTP 503), and has no saved copy, so they are missing.",
        ])
    })

    test('an agent gets the result as JSON, with the files read and where the skills came from', async () => {
        const result = await learn(['posthog:instrument-integration'], fakeSkills())

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
            'Run `hog learn skills` to list every skill.',
            1,
        ],
        [
            { code: 'unknown_file', message: 'Unknown file: "nope.md".' },
            'unknown_file',
            'Give the path from the skill folder, such as references/COMMANDMENTS.md.',
            1,
        ],
        [
            { code: 'usage', message: 'Usage: hog learn <source>:<skill> <path> --lines <start>:<end>' },
            'invalid_learn_command',
            'Run `hog learn` to see the commands.',
            2,
        ],
    ] as const)('a %j failure is the HogError %s', async (error, code, hint, exitCode) => {
        const result = await learn(['posthog:instrument-integration', 'nope.md'], fakeSkills(error))

        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, message: expect.stringContaining(error.message), hint })
    })

    test.each([
        [['-s', 'replay', '--lines', '1:2'], 'invalid_learn_command'],
        [['posthog:funnels', 'SKILL.md', '--lines', 'ten'], 'invalid_input'],
    ])('hog learn %j fails before it loads the skills', async (argv, code) => {
        const skills = fakeSkills()

        const result = await learn(argv, skills)

        expect(result.exitCode).toBe(2)
        expect(result.error().code).toBe(code)
        expect(skills.calls).toEqual([])
    })

    test('the usage event names the skills read and how, but not the search keywords', async () => {
        const result = await runHog(['learn', 'posthog:instrument-integration', 'SKILL.md', '-s', 'secret-keywords'], {
            env: { CLAUDECODE: '1' },
            telemetryToken: 'phc_test',
            skills: fakeSkills({
                ...READ,
                reads: [
                    { source: 'posthog', skill: 'instrument-integration', path: 'SKILL.md', readKind: 'file_search' },
                ],
            }).library,
            respond: () => ({ status: 200, body: {} }),
        })

        const batch = result.requests
            .filter((request) => request.url === 'https://us.i.posthog.com/batch/')
            .flatMap((request) => (request.body as { batch: unknown[] }).batch)
        expect(batch).toEqual([
            expect.objectContaining({
                event: 'posthog cli command run',
                properties: expect.objectContaining({
                    command_path: 'learn',
                    options: ['search'],
                    learn_kind: 'text',
                    skills_read: ['posthog:instrument-integration'],
                    read_kinds: ['file_search'],
                    skill_asset_origins: { 'product-skills': 'network', 'context-mill': 'network' },
                }),
            }),
        ])
        expect(JSON.stringify(batch)).not.toContain('secret-keywords')
    })
})
