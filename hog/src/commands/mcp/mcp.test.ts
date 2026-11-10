import { describe, expect, test } from 'bun:test'
import { parse } from 'jsonc-parser'

import type { Env } from '@/core/runtime'
import { runHog, type FakeRuntimeOptions, type HogRun } from '@/testing'

const URL = 'https://mcp.posthog.com/mcp'
const HOME = '/home/test'
const REPOSITORY = { '/work/.git/HEAD': 'ref: refs/heads/main\n' }
const OTHER = { command: 'other-server' }

function mcp(argv: string[], env: Env, options: FakeRuntimeOptions = {}): Promise<HogRun> {
    return runHog(['mcp', 'add', ...argv], {
        cwd: '/work/app',
        ...options,
        env,
        files: { ...REPOSITORY, ...options.files },
    })
}

function json(text: string | undefined): unknown {
    return parse(text ?? '')
}

describe('hog mcp add', () => {
    test.each<[string, string, string, string, Record<string, unknown>]>([
        [
            'claude-code',
            '/work/.mcp.json',
            '{\n  "mcpServers": {"other": {"command": "other-server"}}\n}\n',
            'mcpServers',
            { type: 'http', url: URL },
        ],
        [
            'cursor',
            `${HOME}/.cursor/mcp.json`,
            '{"mcpServers": {"other": {"command": "other-server"}}}',
            'mcpServers',
            { url: URL },
        ],
        [
            'vscode',
            `${HOME}/.config/Code/User/mcp.json`,
            '{"servers": {"other": {"command": "other-server"}}}',
            'servers',
            { type: 'http', url: URL },
        ],
        [
            'zed',
            `${HOME}/.config/zed/settings.json`,
            '{\n  // my theme\n  "theme": "One Dark",\n  "context_servers": {"other": {"command": "other-server"},},\n}\n',
            'context_servers',
            { enabled: true, url: URL },
        ],
        [
            'opencode',
            `${HOME}/.config/opencode/opencode.json`,
            '{"mcp": {"other": {"command": "other-server"}}}',
            'mcp',
            { type: 'remote', url: URL },
        ],
    ])('%s gets the entry in %s, next to the servers already there', async (agent, path, before, key, entry) => {
        const result = await mcp(['--agent', agent], {}, { files: { [path]: before } })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({ added: [{ agent, path, status: 'added' }] })
        expect(json(result.files[path])).toMatchObject({ [key]: { other: OTHER, posthog: entry } })
        for (const comment of before.match(/\/\/.*$/gm) ?? []) {
            expect(result.files[path]).toContain(comment)
        }
    })

    test('codex gets a TOML section after the config already there', async () => {
        const path = `${HOME}/.codex/config.toml`
        const before = 'model = "o3"\n\n[mcp_servers.other]\ncommand = "other-server"\n'

        const result = await mcp(['--agent', 'codex'], {}, { files: { [path]: before } })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({ added: [{ agent: 'codex', path, status: 'added' }] })
        expect(result.files[path]).toBe(`${before}\n[mcp_servers.posthog]\nurl = "${URL}"\nstartup_timeout_sec = 30\n`)
    })

    test.each<[string, Record<string, string>, string[], string, 'already_added' | 'replaced' | 'added', string]>([
        [
            'an entry in the file is kept',
            { [`${HOME}/.cursor/mcp.json`]: '{"mcpServers": {"posthog": {"url": "https://old.example.com"}}}' },
            ['--agent', 'cursor'],
            `${HOME}/.cursor/mcp.json`,
            'already_added',
            'https://old.example.com',
        ],
        [
            'an entry in the file is replaced with --force',
            { [`${HOME}/.cursor/mcp.json`]: '{"mcpServers": {"posthog": {"url": "https://old.example.com"}}}' },
            ['--agent', 'cursor', '--force'],
            `${HOME}/.cursor/mcp.json`,
            'replaced',
            URL,
        ],
        [
            "the Wizard's quoted Codex section is kept",
            { [`${HOME}/.codex/config.toml`]: '[mcp_servers."posthog"]\nurl = "https://old.example.com"\n' },
            ['--agent', 'codex'],
            `${HOME}/.codex/config.toml`,
            'already_added',
            'https://old.example.com',
        ],
        [
            "the Wizard's quoted Codex section is updated in place with --force",
            { [`${HOME}/.codex/config.toml`]: '[mcp_servers."posthog"]\nurl = "https://old.example.com"\n' },
            ['--agent', 'codex', '--force'],
            `${HOME}/.codex/config.toml`,
            'replaced',
            URL,
        ],
        [
            "the Wizard's user entry for Claude Code counts",
            {
                [`${HOME}/.claude.json`]:
                    '{"mcpServers": {"posthog": {"type": "http", "url": "https://old.example.com"}}}',
            },
            ['--agent', 'claude-code'],
            `${HOME}/.claude.json`,
            'already_added',
            'https://old.example.com',
        ],
        [
            "--force adds the project entry next to the Wizard's user entry",
            {
                [`${HOME}/.claude.json`]:
                    '{"mcpServers": {"posthog": {"type": "http", "url": "https://old.example.com"}}}',
            },
            ['--agent', 'claude-code', '--force'],
            '/work/.mcp.json',
            'added',
            URL,
        ],
    ])('%s', async (_name, files, argv, path, status, url) => {
        const result = await mcp(argv, {}, { files })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ added: [{ path, status }] })
        expect(result.files[path]?.match(/https:\/\/[^"]+/g)).toEqual([url])
    })

    test.each<[string, Env, Record<string, string>]>([
        ['no login', {}, {}],
        ['a US host', { HOG_HOST: 'https://us.posthog.com' }, {}],
        ['an EU host in posthog.json', {}, { '/work/app/posthog.json': '{"host": "https://eu.posthog.com"}' }],
    ])("%s gets the Wizard's server URL", async (_name, env, files) => {
        const result = await mcp(['--agent', 'cursor'], env, { files })

        expect(result.exitCode).toBe(0)
        expect(json(result.files[`${HOME}/.cursor/mcp.json`])).toEqual({ mcpServers: { posthog: { url: URL } } })
    })

    test('a self-hosted host is refused before anything is written', async () => {
        const result = await mcp(['--agent', 'cursor'], { HOG_HOST: 'https://ph.example.com' })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'mcp_self_hosted', hint: expect.stringContaining('--host') })
        expect(Object.keys(result.files)).toEqual(Object.keys(REPOSITORY))
    })

    test('no key reaches a config file, even with a personal API key in the environment', async () => {
        const env = { HOG_PERSONAL_API_KEY: 'phx_secret_key', HOG_PROJECT_ID: '7', HOG_HOST: 'https://eu.posthog.com' }

        const result = await mcp(['--agent', 'cursor', '--agent', 'codex', '--agent', 'claude-code'], env)

        expect(result.exitCode).toBe(0)
        for (const path of [`${HOME}/.cursor/mcp.json`, `${HOME}/.codex/config.toml`, '/work/.mcp.json']) {
            expect(result.files[path]).toContain(URL)
            expect(result.files[path]).not.toMatch(/phx_|Authorization|headers|POSTHOG_AUTH_HEADER/)
        }
        expect(result.requests).toEqual([])
    })

    test.each<[string, string[], Env, string, number]>([
        ['an agent hog has no entry for', ['--agent', 'windsurf'], {}, 'unknown_agent', 2],
        ['no agent running hog', [], {}, 'mcp_agent_required', 2],
        ['a detected agent hog has no entry for', [], { GEMINI_CLI: '1' }, 'mcp_agent_required', 2],
        [
            'a client with no settings path on Linux',
            ['--agent', 'cursor', '--agent', 'claude-desktop'],
            {},
            'mcp_unsupported_platform',
            1,
        ],
    ])('%s fails before anything is written', async (_name, argv, env, code, exitCode) => {
        const result = await mcp(argv, env)

        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code })
        if (exitCode === 2) {
            expect(result.error().hint).toBe(
                'Pass `--agent` with one of: claude-code, cursor, codex, vscode, zed, opencode, claude-desktop.'
            )
        }
        expect(Object.keys(result.files)).toEqual(Object.keys(REPOSITORY))
    })

    test.each<[string, string, string | null]>([
        ['a link out of the repository is refused', '/outside/mcp.json', null],
        ['a link inside the repository is written through', '/work/config/mcp.json', '/work/config/mcp.json'],
    ])('%s', async (_name, target, written) => {
        const files = { [target]: '{}', '/outside/notes.txt': 'keep' }

        const result = await mcp(['--agent', 'claude-code'], {}, { files, links: { '/work/.mcp.json': target } })

        if (written === null) {
            expect(result.exitCode).toBe(1)
            expect(result.error()).toMatchObject({ code: 'unsafe_mcp_config_path' })
            expect(result.files[target]).toBe('{}')
        } else {
            expect(result.exitCode).toBe(0)
            expect(json(result.files[written])).toEqual({ mcpServers: { posthog: { type: 'http', url: URL } } })
        }
        expect(result.files['/work/.mcp.json']).toBeUndefined()
    })

    test('a person is told how the agent logs in, and the detected agent is used', async () => {
        const result = await mcp(['-o', 'text'], { CLAUDECODE: '1', NO_COLOR: '1' })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toBe(
            [
                'Added the PostHog MCP server to Claude Code in /work/.mcp.json.',
                'Claude Code asks you to approve the server in this repository. Then run `claude mcp login posthog` to log in to PostHog.',
                '',
            ].join('\n')
        )
    })
})
