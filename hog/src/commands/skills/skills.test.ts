import { describe, expect, test } from 'bun:test'
import { join } from 'node:path'

import type {
    InstallableSkill,
    SkillAssetStatus,
    SkillsLibrary,
    SkillsRelease,
} from '@posthog/mcp/src/cli/library-types'

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

const CATALOG: InstallableSkill[] = [
    {
        id: 'posthog-flags',
        name: 'Feature flags',
        description: 'Roll out a change behind a flag.\nThen clean the flag up.',
        tags: [],
    },
    { id: 'posthog-replay', name: 'Session replay', description: 'Watch what people did.', tags: [] },
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

function fakeSkills(installed: string[] = []): FakeSkills {
    const calls: InstallCall[] = []
    const present = new Set(installed)
    const release: SkillsRelease = { assets: ASSETS }

    const fake: FakeSkills = {
        calls,
        releaseLoads: 0,
        library: () => library,
    }

    const library: SkillsLibrary = {
        learn: async () => ({ ok: false, error: { code: 'usage', message: 'not used' } }),
        instrumentSkills: async () => ({ ok: true, value: { skills: [], assets: ASSETS } }),
        installable: async () => {
            fake.releaseLoads += 1
            return { ok: true, value: { skills: CATALOG, assets: ASSETS, release } }
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

        const result = await skills(['add', 'posthog-flags', ...flags], fake, env)

        expect(result.exitCode).toBe(0)
        expect(fake.calls).toEqual([{ id: 'posthog-flags', cwd: '/work', force: false, skillsDir: folder }])
        expect(result.json()).toEqual({
            root: '/work',
            rootKind: 'repository',
            agentSource,
            skills: [{ id: 'posthog-flags', agent, path: `/work/${folder}/posthog-flags`, status: 'installed' }],
            assets: ASSETS,
        })
    })

    test('--agent repeats, agents that share a folder share one copy, and every install reuses one release', async () => {
        const fake = fakeSkills()

        const result = await skills(
            ['add', 'posthog-flags', '--agent', 'claude-code', '--agent', 'codex', '--agent', 'cursor'],
            fake,
            {}
        )

        expect(result.exitCode).toBe(0)
        expect(fake.calls.map((call) => call.skillsDir)).toEqual(['.claude/skills', '.agents/skills'])
        expect(fake.releaseLoads).toBe(1)
        expect(result.json()).toMatchObject({
            skills: [
                { agent: 'claude-code', path: '/work/.claude/skills/posthog-flags', status: 'installed' },
                { agent: 'codex', path: '/work/.agents/skills/posthog-flags', status: 'installed' },
                { agent: 'cursor', path: '/work/.agents/skills/posthog-flags', status: 'installed' },
            ],
        })
    })

    test('a person outside a git repository is told where the skills went', async () => {
        const fake = fakeSkills()

        const result = await skills(
            ['add', 'posthog-flags'],
            fake,
            { NO_COLOR: '1' },
            { cwd: '/scratch', stdoutIsTTY: true }
        )

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toBe(
            [
                "/scratch isn't in a git repository, so the skills go in this folder.",
                'No agent is running hog, so the skills go in .agents/skills, which most agents read.',
                'Pass --agent to pick one, such as --agent claude-code.',
                'Installed posthog-flags in .agents/skills/posthog-flags',
                '',
            ].join('\n')
        )
    })

    test.each<[string, string[], boolean | undefined, 'installed' | 'already_installed']>([
        ['without --force keeps', [], false, 'already_installed'],
        ['with --force replaces', ['--force'], true, 'installed'],
    ])('an installed skill %s the copy', async (_name, flags, force, status) => {
        const fake = fakeSkills(['/work/.claude/skills/posthog-flags'])

        const result = await skills(['add', 'posthog-flags', ...flags], fake, { CLAUDECODE: '1' })

        expect(result.exitCode).toBe(0)
        expect(fake.calls).toEqual([{ id: 'posthog-flags', cwd: '/work', force, skillsDir: '.claude/skills' }])
        expect(result.json()).toMatchObject({ skills: [{ id: 'posthog-flags', status }] })
    })

    test('an unknown id fails before any skill is installed, and the hint names hog skills list', async () => {
        const fake = fakeSkills()

        const result = await skills(['add', 'posthog-flags', 'posthog-nope'], fake, { CLAUDECODE: '1' })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({
            code: 'unknown_skill',
            message: 'Unknown skill "posthog-nope".',
            hint: 'Run `hog skills list` to see the skills you can add.',
        })
        expect(fake.calls).toEqual([])
    })

    test('hog skills list shows each skill with the first line of its description', async () => {
        const fake = fakeSkills()

        const result = await skills(['list'], fake, { CLAUDECODE: '1' })

        expect(result.exitCode).toBe(0)
        expect(result.requests).toEqual([])
        expect(result.json()).toEqual({
            skills: [
                { id: 'posthog-flags', name: 'Feature flags', description: 'Roll out a change behind a flag.' },
                { id: 'posthog-replay', name: 'Session replay', description: 'Watch what people did.' },
            ],
            assets: ASSETS,
        })
    })
})
