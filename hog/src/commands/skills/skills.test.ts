import { describe, expect, test } from 'bun:test'
import { join } from 'node:path'

import type { CatalogSkill, SkillAssetStatus, SkillsLibrary, SkillsRelease } from '@posthog/mcp/src/cli/library-types'

import type { Env } from '@/core/runtime'
import { runHog, type FakeRuntimeOptions, type HogRun } from '@/testing'

const ASSETS: SkillAssetStatus[] = [
    {
        name: 'context-mill',
        url: 'https://example.com/context-mill.zip',
        origin: 'network',
        fetchedAt: '2026-01-01T00:00:00.000Z',
    },
]

const CATALOG: CatalogSkill[] = [
    { name: 'analyzing-funnels', kind: 'learning', description: 'Find where people drop off.' },
    { name: 'tracing-nodejs', kind: 'implementation', description: 'Trace requests in Node.js.' },
]

interface InstallCall {
    id: string
    cwd: string
    force: boolean | undefined
    skillsDir: string | undefined
}

interface FakeSkills {
    library: () => SkillsLibrary
    calls: InstallCall[]
    releaseLoads: number
}

function fakeSkills(installed: string[] = [], assets = ASSETS): FakeSkills {
    const calls: InstallCall[] = []
    const present = new Set(installed)
    const release: SkillsRelease = { assets }

    const fake: FakeSkills = {
        calls,
        releaseLoads: 0,
        library: () => library,
    }

    const library: SkillsLibrary = {
        read: async () => ({ ok: false, error: { code: 'usage', message: 'not used' } }),
        search: async () => ({ ok: false, error: { code: 'usage', message: 'not used' } }),
        instrumentSkills: async () => ({ ok: true, value: { skills: [], assets: ASSETS } }),
        catalog: async () => {
            fake.releaseLoads += 1
            return { ok: true, value: { skills: CATALOG, assets, release } }
        },
        install: async (id, { cwd, force, skillsDir, release: given }) => {
            calls.push({ id, cwd, force, skillsDir })
            if (given !== release) {
                fake.releaseLoads += 1
            }

            const directory = join(cwd, skillsDir ?? '.agents/skills', id)
            if (present.has(directory) && !force) {
                return {
                    ok: false,
                    error: { code: 'already_installed', message: `Skill "${id}" is already installed.` },
                }
            }

            present.add(directory)
            return { ok: true, value: { skill: { id, directory, fileCount: 1 }, assets: ASSETS } }
        },
    }

    return fake
}

const REPOSITORY: FakeRuntimeOptions = { cwd: '/work/app', files: { '/work/.git/HEAD': 'ref: refs/heads/main\n' } }

function skills(argv: string[], fake: FakeSkills, env: Env, options = REPOSITORY): Promise<HogRun> {
    return runHog(['skills', ...argv], { ...options, env, skills: fake.library })
}

describe('hog skills', () => {
    test.each<[string, Env, string[], string, string | null, 'detected' | 'option' | 'none']>([
        ['Claude Code', { CLAUDECODE: '1' }, [], '.claude/skills', 'claude-code', 'detected'],
        [
            'Claude Code with a versioned AI_AGENT',
            { AI_AGENT: 'claude-code_9-9-9_agent', CLAUDECODE: '1' },
            [],
            '.claude/skills',
            'claude-code',
            'detected',
        ],
        ['an agent hog has no folder for', { AI_AGENT: 'some-agent' }, [], '.agents/skills', 'some-agent', 'detected'],
        [
            '--agent over the detected agent',
            { CLAUDECODE: '1' },
            ['--agent', 'codex'],
            '.agents/skills',
            'codex',
            'option',
        ],
        ['no agent', {}, [], '.agents/skills', null, 'none'],
    ])('%s installs into %s of the repository root', async (_name, env, flags, folder, agent, agentSource) => {
        const fake = fakeSkills()

        const result = await skills(['add', 'posthog:tracing-nodejs', ...flags], fake, env)

        expect(result.exitCode).toBe(0)
        expect(fake.calls).toEqual([{ id: 'tracing-nodejs', cwd: '/work', force: false, skillsDir: folder }])
        expect(result.json()).toEqual({
            root: '/work',
            rootKind: 'repository',
            agentSource,
            skills: [
                {
                    name: 'tracing-nodejs',
                    agent,
                    path: `/work/${folder}/tracing-nodejs`,
                    status: 'installed',
                },
            ],
            assets: ASSETS,
        })
    })

    test('--agent repeats, agents that share a folder share one copy, and every install reuses one release', async () => {
        const fake = fakeSkills()

        const result = await skills(
            ['add', 'posthog:tracing-nodejs', '--agent', 'claude-code', '--agent', 'codex', '--agent', 'cursor'],
            fake,
            {}
        )

        expect(result.exitCode).toBe(0)
        expect(fake.calls.map((call) => call.skillsDir)).toEqual(['.claude/skills', '.agents/skills'])
        expect(fake.releaseLoads).toBe(1)
        expect(result.json()).toMatchObject({
            skills: [
                { agent: 'claude-code', path: '/work/.claude/skills/tracing-nodejs', status: 'installed' },
                { agent: 'codex', path: '/work/.agents/skills/tracing-nodejs', status: 'installed' },
                { agent: 'cursor', path: '/work/.agents/skills/tracing-nodejs', status: 'installed' },
            ],
        })
    })

    test.each<[string, string[], string[]]>([
        ['a new skill', [], ['✓ Added analyzing-funnels to /scratch', '  Wrote .agents/skills/analyzing-funnels']],
        [
            'a skill that is already there',
            ['/scratch/.agents/skills/analyzing-funnels'],
            [
                '• Nothing to add: analyzing-funnels is already in /scratch',
                '  Left .agents/skills/analyzing-funnels as it was, because the skill is already there',
            ],
        ],
    ])('a person who adds %s sees the result first, then the folder, then the notes', async (_name, installed, top) => {
        const fake = fakeSkills(installed)

        const result = await skills(
            ['add', 'analyzing-funnels'],
            fake,
            { NO_COLOR: '1' },
            { cwd: '/scratch', stdoutIsTTY: true }
        )

        expect(result.exitCode).toBe(0)
        expect(result.stdout.split('\n').slice(0, 5)).toEqual([
            ...top,
            '',
            "/scratch isn't in a git repository, so the skills went in this folder.",
            'No agent is running hog, so the skills went in .agents/skills, which most agents read. To add them for one agent, pass --agent, as in --agent claude-code.',
        ])
    })

    test.each<[string, string[], boolean | undefined, 'installed' | 'already_installed']>([
        ['without --force keeps', [], false, 'already_installed'],
        ['with --force replaces', ['--force'], true, 'installed'],
    ])('an installed skill %s the copy', async (_name, flags, force, status) => {
        const fake = fakeSkills(['/work/.claude/skills/tracing-nodejs'])

        const result = await skills(['add', 'tracing-nodejs', ...flags], fake, { CLAUDECODE: '1' })

        expect(result.exitCode).toBe(0)
        expect(fake.calls).toEqual([{ id: 'tracing-nodejs', cwd: '/work', force, skillsDir: '.claude/skills' }])
        expect(result.json()).toMatchObject({ skills: [{ name: 'tracing-nodejs', status }] })
    })

    const OUTAGE: SkillAssetStatus[] = [
        ...ASSETS,
        { name: 'product-skills', url: 'https://example.com/skills.zip', origin: 'unavailable', failure: 'HTTP 503' },
    ]

    test.each([
        [
            'fails as unknown, and the hint names hog skills list',
            ASSETS,
            {
                code: 'unknown_skill',
                message: 'Unknown skill "nope".',
                hint: 'Run `hog skills list` to see every skill you can add.',
            },
        ],
        [
            'fails as offline while a download is missing, because the skill may be in it',
            OUTAGE,
            {
                code: 'skills_offline',
                message: `Couldn't download all the PostHog skills, so hog can't check "nope".\n  https://example.com/skills.zip: HTTP 503`,
            },
        ],
    ])('a skill missing from the list %s, before any skill is installed', async (_name, assets, error) => {
        const fake = fakeSkills([], assets)

        const result = await skills(['add', 'tracing-nodejs', 'nope'], fake, { CLAUDECODE: '1' })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject(error)
        expect(fake.calls).toEqual([])
    })

    test('hog skills list shows both kinds to a person, and only names, grouped by kind, to an agent', async () => {
        const fake = fakeSkills()

        const person = await skills(['list'], fake, { NO_COLOR: '1' }, { ...REPOSITORY, stdoutIsTTY: true })
        const agent = await skills(['list'], fake, { CLAUDECODE: '1' })

        const lines = person.stdout.split('\n')
        expect(lines[0]).toBe('Skills for using PostHog (1)')
        expect(lines.find((line) => line.includes('analyzing-funnels'))).toContain('Find where people drop off.')
        expect(lines).toContain('Skills for adding PostHog to your code (1)')
        expect(lines.at(-2)).toBe(
            '2 skills. Read one with hog skills read <skill>, or add it to this repository with hog skills add <skill...>.'
        )
        expect(agent.json()).toEqual({ learning: ['analyzing-funnels'], implementation: ['tracing-nodejs'] })
    })

    test('hog skills alone says how to list, read and add skills', async () => {
        const result = await skills([], fakeSkills(), { NO_COLOR: '1' }, { ...REPOSITORY, stdoutIsTTY: true })

        expect(result.exitCode).toBe(0)
        expect(result.stderr).toBe('')
        expect(result.stdout).toContain('hog skills list')
        expect(result.stdout).toContain('hog skills add <skill...>')
    })
})
