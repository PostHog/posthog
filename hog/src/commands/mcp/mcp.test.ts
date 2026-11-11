import { describe, expect, test } from 'bun:test'
import { parse } from 'jsonc-parser'

import type { Env } from '@/core/runtime'
import { runHog, type FakeRuntimeOptions, type HogRun } from '@/testing'

const URL = 'https://mcp.posthog.com/mcp'
const WIZARD_URL = 'https://mcp.posthog.com/mcp?features=flags,insights'
const FOREIGN_URL = 'https://mcp.example.com/mcp'
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
    test.each<[string, string, string, string, Record<string, unknown>, NodeJS.Platform]>([
        [
            'claude-code',
            '/work/.mcp.json',
            '{\n  "mcpServers": {"other": {"command": "other-server"}}\n}\n',
            'mcpServers',
            { type: 'http', url: URL },
            'linux',
        ],
        [
            'cursor',
            `${HOME}/.cursor/mcp.json`,
            '{"mcpServers": {"other": {"command": "other-server"}}}',
            'mcpServers',
            { url: URL },
            'linux',
        ],
        [
            'vscode',
            `${HOME}/.config/Code/User/mcp.json`,
            '{"servers": {"other": {"command": "other-server"}}}',
            'servers',
            { type: 'http', url: URL },
            'linux',
        ],
        [
            'zed',
            `${HOME}/.config/zed/settings.json`,
            '{\n  // my theme\n  "theme": "One Dark",\n  "context_servers": {"other": {"command": "other-server"},},\n}\n',
            'context_servers',
            { enabled: true, url: URL },
            'linux',
        ],
        [
            'opencode',
            `${HOME}/.config/opencode/opencode.json`,
            '{"mcp": {"other": {"command": "other-server"}}}',
            'mcp',
            { type: 'remote', url: URL },
            'linux',
        ],
        [
            'claude-desktop',
            `${HOME}/Library/Application Support/Claude/claude_desktop_config.json`,
            '{"mcpServers": {"other": {"command": "other-server"}}}',
            'mcpServers',
            { command: 'npx', args: ['-y', expect.stringMatching(/^mcp-remote@\d+\.\d+\.\d+$/), URL] },
            'darwin',
        ],
    ])(
        '%s gets the entry in %s, next to the servers already there',
        async (agent, path, before, key, entry, platform) => {
            const result = await mcp(['--agent', agent], {}, { platform, files: { [path]: before } })

            expect(result.exitCode).toBe(0)
            expect(result.json()).toEqual({ added: [{ agent, path, status: 'added' }] })
            expect(json(result.files[path])).toMatchObject({ [key]: { other: OTHER, posthog: entry } })
            for (const comment of before.match(/\/\/.*$/gm) ?? []) {
                expect(result.files[path]).toContain(comment)
            }
        }
    )

    test.each<[string, Env, string]>([
        ['~/.codex', {}, `${HOME}/.codex/config.toml`],
        ['CODEX_HOME', { CODEX_HOME: '/work/codex' }, '/work/codex/config.toml'],
    ])('codex gets a TOML section after the config already there, in %s', async (_name, env, path) => {
        const before = 'model = "o3"\n\n[mcp_servers.other]\ncommand = "other-server"\n'

        const result = await mcp(['--agent', 'codex'], env, { files: { [path]: before } })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({ added: [{ agent: 'codex', path, status: 'added' }] })
        expect(result.files[path]).toBe(`${before}\n[mcp_servers.posthog]\nurl = "${URL}"\nstartup_timeout_sec = 30\n`)
    })

    test.each<[string, Record<string, string>, string[], string, 'already_added' | 'replaced' | 'added', string]>([
        [
            "an entry in the file with the Wizard's URL is kept",
            { [`${HOME}/.cursor/mcp.json`]: `{"mcpServers": {"posthog": {"url": "${WIZARD_URL}"}}}` },
            ['--agent', 'cursor'],
            `${HOME}/.cursor/mcp.json`,
            'already_added',
            WIZARD_URL,
        ],
        [
            'an entry for the EU host is kept',
            { [`${HOME}/.cursor/mcp.json`]: '{"mcpServers": {"posthog": {"url": "https://mcp-eu.posthog.com/mcp"}}}' },
            ['--agent', 'cursor'],
            `${HOME}/.cursor/mcp.json`,
            'already_added',
            'https://mcp-eu.posthog.com/mcp',
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
            { [`${HOME}/.codex/config.toml`]: `[mcp_servers."posthog"]\nurl = "${WIZARD_URL}"\n` },
            ['--agent', 'codex'],
            `${HOME}/.codex/config.toml`,
            'already_added',
            WIZARD_URL,
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
            'a Codex header with spaces, single quotes and a comment is kept',
            {
                [`${HOME}/.codex/config.toml`]: `  [ mcp_servers . 'posthog' ] # PostHog\nurl = "${URL}"\n`,
            },
            ['--agent', 'codex'],
            `${HOME}/.codex/config.toml`,
            'already_added',
            URL,
        ],
        [
            "the Wizard's user entry for Claude Code counts",
            { [`${HOME}/.claude.json`]: `{"mcpServers": {"posthog": {"type": "http", "url": "${WIZARD_URL}"}}}` },
            ['--agent', 'claude-code'],
            `${HOME}/.claude.json`,
            'already_added',
            WIZARD_URL,
        ],
        [
            'the user entry `claude mcp add` writes for mcp-remote counts',
            {
                [`${HOME}/.claude.json`]: `{"mcpServers": {"posthog": {"type": "stdio", "command": "npx", "args": ["-y", "mcp-remote", "${URL}"], "env": {}}}}`,
            },
            ['--agent', 'claude-code'],
            `${HOME}/.claude.json`,
            'already_added',
            URL,
        ],
        [
            "a user entry for Claude Code that points at another server doesn't count",
            { [`${HOME}/.claude.json`]: `{"mcpServers": {"posthog": {"type": "http", "url": "${FOREIGN_URL}"}}}` },
            ['--agent', 'claude-code'],
            '/work/.mcp.json',
            'added',
            URL,
        ],
        [
            'a project entry that points at another server is replaced with --force',
            { '/work/.mcp.json': `{"mcpServers": {"posthog": {"type": "http", "url": "${FOREIGN_URL}"}}}` },
            ['--agent', 'claude-code', '--force'],
            '/work/.mcp.json',
            'replaced',
            URL,
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

    test.each<[string, string, string, string, NodeJS.Platform, string | null]>([
        [
            'a project entry for another URL',
            'claude-code',
            '/work/.mcp.json',
            `{"mcpServers": {"posthog": {"type": "http", "url": "${FOREIGN_URL}"}}}`,
            'linux',
            FOREIGN_URL,
        ],
        [
            'a URL with credentials in it',
            'cursor',
            `${HOME}/.cursor/mcp.json`,
            '{"mcpServers": {"posthog": {"url": "https://user:example-secret@mcp.example.com/mcp?token=example-token"}}}',
            'linux',
            'https://mcp.example.com/mcp',
        ],
        [
            "a host that starts with PostHog's",
            'cursor',
            `${HOME}/.cursor/mcp.json`,
            '{"mcpServers": {"posthog": {"url": "https://mcp.posthog.com.example.com/mcp"}}}',
            'linux',
            'https://mcp.posthog.com.example.com/mcp',
        ],
        [
            'a Codex section for another URL',
            'codex',
            `${HOME}/.codex/config.toml`,
            `[mcp_servers.posthog]\nurl = "${FOREIGN_URL}" # ${URL}\n`,
            'linux',
            FOREIGN_URL,
        ],
        [
            'an mcp-remote entry for another URL',
            'claude-desktop',
            `${HOME}/Library/Application Support/Claude/claude_desktop_config.json`,
            `{"mcpServers": {"posthog": {"command": "npx", "args": ["-y", "mcp-remote@0.16.5", "${FOREIGN_URL}"]}}}`,
            'darwin',
            FOREIGN_URL,
        ],
        [
            'an mcp-remote entry that npx installs from another package',
            'claude-desktop',
            `${HOME}/Library/Application Support/Claude/claude_desktop_config.json`,
            `{"mcpServers": {"posthog": {"command": "npx", "args": ["-y", "-p", "example-bridge", "mcp-remote", "${URL}"]}}}`,
            'darwin',
            null,
        ],
        [
            'an mcp-remote entry that npx installs from an npm alias',
            'claude-desktop',
            `${HOME}/Library/Application Support/Claude/claude_desktop_config.json`,
            `{"mcpServers": {"posthog": {"command": "npx", "args": ["-y", "mcp-remote@npm:example-bridge@1.0.0", "${URL}"]}}}`,
            'darwin',
            null,
        ],
        [
            "a project mcp-remote entry for PostHog's URL",
            'claude-code',
            '/work/.mcp.json',
            `{"mcpServers": {"posthog": {"command": "npx", "args": ["-y", "mcp-remote", "${URL}"]}}}`,
            'linux',
            null,
        ],
        [
            'an mcp-remote entry with an env',
            'claude-desktop',
            `${HOME}/Library/Application Support/Claude/claude_desktop_config.json`,
            `{"mcpServers": {"posthog": {"command": "npx", "args": ["-y", "mcp-remote@0.16.5", "${URL}"], "env": {"NODE_OPTIONS": "--require ./example.js"}}}}`,
            'darwin',
            null,
        ],
        [
            'a Codex mcp-remote section with an env table',
            'codex',
            `${HOME}/.codex/config.toml`,
            `[mcp_servers.posthog]\ncommand = "npx"\nargs = ["-y", "mcp-remote", "${URL}"]\n\n[mcp_servers.posthog.env]\nnpm_config_registry = "https://registry.example.com"\n`,
            'linux',
            null,
        ],
        [
            'a Codex mcp-remote section with env_vars',
            'codex',
            `${HOME}/.codex/config.toml`,
            `[mcp_servers.posthog]\ncommand = "npx"\nargs = ["-y", "mcp-remote", "${URL}"]\nenv_vars = ["PATH"]\n`,
            'linux',
            null,
        ],
    ])(
        '%s is refused without --force, and the file stays as it was',
        async (_name, agent, path, before, platform, url) => {
            const result = await mcp(['--agent', agent], {}, { platform, files: { [path]: before } })

            expect(result.exitCode).toBe(1)
            expect(result.error()).toMatchObject({
                code: 'mcp_foreign_server',
                message: expect.stringContaining(path),
                hint: expect.stringContaining('--force'),
            })
            if (url !== null) {
                expect(result.error().message).toContain(`points at ${url},`)
            }
            expect(result.stderr + result.stdout).not.toContain('example-secret')
            expect(result.stderr + result.stdout).not.toContain('example-token')
            expect(result.files[path]).toBe(before)
        }
    )

    test.each<[string, string, string]>([
        [
            'stops at an indented header, and leaves the next server as it was',
            '[mcp_servers.posthog]\nurl = "https://old.example.com"\n\n  [mcp_servers.other]\nstartup_timeout_sec = 60\n',
            `[mcp_servers.posthog]\nstartup_timeout_sec = 30\nurl = "${URL}"\n\n  [mcp_servers.other]\nstartup_timeout_sec = 60\n`,
        ],
        [
            'drops the stdio fields of an mcp-remote entry, across lines and tables',
            [
                '[mcp_servers.posthog]',
                'command = "npx"',
                'args = [',
                '  "-y",',
                '  "mcp-remote",',
                '  "[mcp_servers.fake]",',
                ']',
                'tool_timeout_sec = 120',
                '',
                '[mcp_servers.posthog.env]',
                'DEBUG = "1"',
                '',
                '[mcp_servers.other]',
                'command = "other-server"',
                '',
            ].join('\n'),
            [
                '[mcp_servers.posthog]',
                `url = "${URL}"`,
                'startup_timeout_sec = 30',
                'tool_timeout_sec = 120',
                '',
                '[mcp_servers.other]',
                'command = "other-server"',
                '',
            ].join('\n'),
        ],
        [
            'drops the auth of a server that pointed elsewhere',
            [
                '[mcp_servers.posthog]',
                'url = "https://mcp.example.com/mcp"',
                'bearer_token_env_var = "EXAMPLE_TOKEN"',
                'env_http_headers = { "X-Team" = "TEAM_ID" }',
                'http_headers_helper = ["example-helper", "--print-headers"]',
                '',
                '[mcp_servers.posthog.http_headers]',
                'Authorization = "Bearer example-not-a-secret"',
                '',
            ].join('\n'),
            ['[mcp_servers.posthog]', 'startup_timeout_sec = 30', `url = "${URL}"`, '', ''].join('\n'),
        ],
    ])('codex --force %s', async (_name, before, after) => {
        const path = `${HOME}/.codex/config.toml`

        const result = await mcp(['--agent', 'codex', '--force'], {}, { files: { [path]: before } })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({ added: [{ agent: 'codex', path, status: 'replaced' }] })
        expect(result.files[path]).toBe(after)
    })

    test.each<[string, string, string, string, string]>([
        [
            'a Codex server written inline',
            'codex',
            `${HOME}/.codex/config.toml`,
            '[mcp_servers]\nposthog = { command = "npx" }\n',
            'mcp_config_not_editable',
        ],
        [
            'a second posthog key in .mcp.json',
            'claude-code',
            '/work/.mcp.json',
            '{"mcpServers": {"posthog": {}, "posthog": {"url": "https://old.example.com"}}}',
            'invalid_mcp_config',
        ],
        [
            'a second mcpServers key in .mcp.json',
            'claude-code',
            '/work/.mcp.json',
            '{"mcpServers": {}, "mcpServers": {"posthog": {"url": "https://old.example.com"}}}',
            'invalid_mcp_config',
        ],
    ])('--force refuses %s and leaves the file as it was', async (_name, agent, path, before, code) => {
        const result = await mcp(['--agent', agent, '--force'], {}, { files: { [path]: before } })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code })
        expect(result.files[path]).toBe(before)
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
                '✓ Added the PostHog MCP server to Claude Code',
                '  Saved in /work/.mcp.json',
                '',
                'Claude Code asks you to approve the server in this repository. Then run `claude mcp login posthog` to log in to PostHog.',
                '',
            ].join('\n')
        )
    })
})
