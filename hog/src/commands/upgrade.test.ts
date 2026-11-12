import { describe, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { readJson, runHog, type FakeRuntimeOptions } from '@/testing'
import type { Manifest } from '@/updates/manifest'

const STABLE = 'https://releases.posthog.com/hog/stable/manifest.json'
const AGENT = { CLAUDECODE: '1' }
// The fake clock starts on 2026-01-01.
const BUILT = '2025-12-20T00:00:00.000Z'
const RUNNING = { version: '0.1.0-alpha.5', date: BUILT }

// A real archive, made by tar, holding a stand-in binary.
const BINARY = new TextEncoder().encode('#!/bin/sh\necho new hog\n')
const ARCHIVE = (() => {
    const folder = mkdtempSync(join(tmpdir(), 'hog-upgrade-'))
    writeFileSync(join(folder, 'hog'), BINARY, { mode: 0o755 })
    const tar = Bun.spawnSync(['tar', '-czf', 'hog.tar.gz', 'hog'], { cwd: folder })
    expect(tar.exitCode).toBe(0)
    return new Uint8Array(readFileSync(join(folder, 'hog.tar.gz')))
})()
const ARCHIVE_SHA = createHash('sha256').update(ARCHIVE).digest('hex')

function manifest(version: string, publishedAt: string, extra: Partial<Manifest> = {}): Manifest {
    return {
        schema: 1,
        name: 'hog',
        version,
        tag: `hog/v${version}`,
        prerelease: version.includes('-'),
        publishedAt,
        buildDate: publishedAt,
        baseUrl: `https://releases.posthog.com/hog/v${version}/`,
        mirrorUrl: `https://github.com/PostHog/posthog/releases/download/hog/v${version}/`,
        artifacts: { 'linux-x64': { file: 'hog-linux-x64.tar.gz', sha256: ARCHIVE_SHA, size: ARCHIVE.length } },
        ...extra,
    }
}

// Answers the manifest at its URL and the archive at the bucket, and fails everything else.
function release(latest: Manifest | null, archive: Uint8Array = ARCHIVE): FakeRuntimeOptions['respond'] {
    return (url) => {
        if (latest && (url === STABLE || url.endsWith(`/v${latest.version}/manifest.json`))) {
            return { status: 200, body: latest }
        }
        if (latest && url === `${latest.baseUrl}hog-linux-x64.tar.gz`) {
            return { status: 200, body: archive }
        }
        return { status: 500, body: {} }
    }
}

const PERSON: FakeRuntimeOptions = { env: { NO_COLOR: '1' }, stdoutIsTTY: true, build: RUNNING }

describe('update notice', () => {
    test.each([
        ['a minor ahead, across prereleases', true, manifest('0.2.0-alpha.1', '2025-12-21T00:00:00Z')],
        ['published more than 30 days after this build', true, manifest('0.1.0-alpha.9', '2026-01-25T00:00:00Z')],
        ['a few patches ahead within a month', false, manifest('0.1.0-alpha.9', '2026-01-10T00:00:00Z')],
        ['the same version', false, manifest('0.1.0-alpha.5', BUILT)],
    ])('%s: shown %p', async (_name, shown, latest) => {
        const result = await runHog(['config', 'schema'], { ...PERSON, respond: release(latest) })

        expect(result.exitCode).toBe(0)
        expect(result.stderr.includes(`hog ${latest.version} is out (you have 0.1.0-alpha.5).`)).toBe(shown)
    })

    test.each([
        ['an agent', { ...PERSON, env: AGENT }],
        ['a pipe', { ...PERSON, stdoutIsTTY: false }],
        ['CI', { ...PERSON, env: { NO_COLOR: '1', CI: 'true' } }],
        [
            'an npx cache',
            { ...PERSON, execPath: '/home/test/.npm/_npx/1a2b/node_modules/@posthog/hog-linux-x64/bin/hog' },
        ],
        ['a run from source', { ...PERSON, isDevelopment: true }],
        ['a local build', { ...PERSON, build: { version: '0.1.0-alpha' } }],
    ])('is not shown to %s', async (_name, options) => {
        const result = await runHog(['config', 'schema'], { ...options, respond: release(manifest('0.3.0', BUILT)) })

        expect(result.exitCode).toBe(0)
        expect(result.stderr).not.toContain('is out')
    })

    const OPT_OUTS: [string, FakeRuntimeOptions][] = [
        ['HOG_NO_UPDATE_CHECK', { env: { ...AGENT, HOG_NO_UPDATE_CHECK: '1' } }],
        ['cli.updateCheck: false', { env: AGENT, files: { '/work/posthog.json': '{"cli": {"updateCheck": false}}' } }],
    ]

    test.each(OPT_OUTS)('%s sends no update request, so not even minimumVersion warns', async (_name, optOut) => {
        const latest = manifest('0.3.0', BUILT, { minimumVersion: '0.2.0' })

        const command = await runHog(['config', 'schema'], { ...optOut, build: RUNNING, respond: release(latest) })
        const status = await runHog(['auth', 'status'], { ...optOut, build: RUNNING, respond: release(latest) })

        expect(command.stderr).toBe('')
        expect(status.json()).toMatchObject({ hog: { latest: null, updateAvailable: false } })
        expect(
            [...command.requests, ...status.requests].filter((request) => request.url.includes('releases.posthog.com'))
        ).toEqual([])
    })

    test.each(OPT_OUTS)('%s still lets setup check for the latest version', async (_name, optOut) => {
        const result = await runHog(['setup'], {
            ...optOut,
            build: RUNNING,
            respond: release(manifest('0.1.0-alpha.6', '2025-12-21T00:00:00Z')),
        })

        expect(result.error()).toMatchObject({ code: 'hog_outdated' })
    })

    test('reads the release at most once a day', async () => {
        const first = await runHog(['config', 'schema'], { ...PERSON, respond: release(manifest('0.2.0', BUILT)) })

        const second = await runHog(['config', 'schema'], { ...PERSON, files: first.files, respond: release(null) })

        expect(first.requests.filter((request) => request.url === STABLE)).toHaveLength(1)
        expect(second.requests.filter((request) => request.url === STABLE)).toHaveLength(0)
        expect(second.stderr).toContain('hog 0.2.0 is out')
    })

    test('a release below minimumVersion warns agents too', async () => {
        const latest = manifest('0.1.0-alpha.7', BUILT, { minimumVersion: '0.1.0-alpha.6' })

        const result = await runHog(['config', 'schema'], { env: AGENT, build: RUNNING, respond: release(latest) })

        expect(result.exitCode).toBe(0)
        expect(readJson(result.stderr)).toEqual({
            warning: {
                code: 'hog_below_minimum_version',
                message: 'hog 0.1.0-alpha.5 has a known problem. Update to 0.1.0-alpha.7.',
                hint: 'Run `hog upgrade`.',
                latest: '0.1.0-alpha.7',
                command: 'hog upgrade',
            },
        })
    })
})

describe('setup on an outdated hog', () => {
    test.each([
        ['a standalone binary', '/usr/local/bin/hog', 'Run `hog upgrade`, then run `hog setup` again.'],
        ['Homebrew', '/opt/homebrew/Cellar/hog/0.1.0/bin/hog', 'Run `brew upgrade hog`, then run `hog setup` again.'],
        [
            'npm',
            '/home/test/.nvm/versions/node/v22.0.0/lib/node_modules/@posthog/hog-linux-x64/bin/hog',
            'Run `npm install -g @posthog/hog@latest`, then run `hog setup` again.',
        ],
        [
            'npx',
            '/home/test/.npm/_npx/1a2b/node_modules/@posthog/hog-linux-x64/bin/hog',
            'Run `npx @posthog/hog@latest setup` to use the latest version.',
        ],
    ])('stops with the command for %s, even one patch behind', async (_name, execPath, hint) => {
        const result = await runHog(['setup'], {
            env: AGENT,
            build: RUNNING,
            execPath,
            respond: release(manifest('0.1.0-alpha.6', '2025-12-21T00:00:00Z')),
        })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'hog_outdated', latest: '0.1.0-alpha.6', hint })
    })

    test('says to update once, without the notice after the error', async () => {
        const result = await runHog(['setup'], { ...PERSON, respond: release(manifest('0.2.0', BUILT)) })

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain('Setup needs the latest hog, 0.2.0')
        expect(result.stderr).not.toContain('is out')
    })

    test('carries on when the release manifest is out of reach', async () => {
        const result = await runHog(['setup'], { env: AGENT, build: RUNNING, respond: release(null) })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            step: 'purpose',
            hog: { version: '0.1.0-alpha.5', latest: null, updateAvailable: false },
        })
    })

    test('asks for a fresh answer, not the daily cache', async () => {
        const anHourAgo = Date.UTC(2026, 0, 1) - 60 * 60 * 1000
        const cache = { checkedAt: anHourAgo, latest: { version: '0.1.0-alpha.5', publishedAt: BUILT } }
        const files = { '/home/test/.config/hog/update-check.json': JSON.stringify(cache) }

        const result = await runHog(['setup'], {
            env: AGENT,
            build: RUNNING,
            files,
            respond: release(manifest('0.1.0-alpha.6', '2025-12-21T00:00:00Z')),
        })

        expect(result.error()).toMatchObject({ code: 'hog_outdated' })
    })

    test('skips the check for a run from source', async () => {
        const result = await runHog(['setup'], {
            env: AGENT,
            build: RUNNING,
            isDevelopment: true,
            respond: release(manifest('0.2.0', BUILT)),
        })

        expect(result.exitCode).toBe(0)
        expect(result.requests.filter((request) => request.url === STABLE)).toHaveLength(0)
    })
})

describe('hog upgrade', () => {
    const NEWER = manifest('0.1.0-alpha.8', '2025-12-30T00:00:00Z')

    test.each([
        ['/opt/homebrew/Cellar/hog/0.1.0/bin/hog', 'homebrew'],
        ['/home/test/.nvm/versions/node/v22.0.0/lib/node_modules/@posthog/hog-linux-x64/bin/hog', 'npm-global'],
        [
            '/home/test/.local/share/pnpm/global/5/.pnpm/@posthog+hog-linux-x64@0.1.0/node_modules/@posthog/hog-linux-x64/bin/hog',
            'pnpm-global',
        ],
        ['/home/test/.bun/install/global/node_modules/@posthog/hog-linux-x64/bin/hog', 'bun-global'],
        ['/home/test/.npm/_npx/1a2b/node_modules/@posthog/hog-linux-x64/bin/hog', 'npx'],
        ['/tmp/bunx-501-@posthog/hog@latest/node_modules/@posthog/hog-linux-x64/bin/hog', 'npx'],
        [
            '/work/app/node_modules/.pnpm/@posthog+hog-linux-x64@0.1.0/node_modules/@posthog/hog-linux-x64/bin/hog',
            'project',
        ],
        ['/usr/local/bin/hog', 'standalone'],
    ])('finds how %s was installed', async (execPath, method) => {
        const result = await runHog(['upgrade', '--check'], {
            env: AGENT,
            build: RUNNING,
            execPath,
            respond: release(NEWER),
        })

        expect(result.json()).toMatchObject({ action: 'available', method })
    })

    test('counts a binary in the folder the install script recorded as a script install', async () => {
        const result = await runHog(['upgrade', '--check'], {
            env: AGENT,
            build: RUNNING,
            execPath: '/home/test/.local/bin/hog',
            files: {
                '/home/test/.config/hog/install.json': '{"method": "script", "install_dir": "/home/test/.local/bin"}',
            },
            respond: release(NEWER),
        })

        expect(result.json()).toMatchObject({ method: 'script', command: 'hog upgrade' })
    })

    test('replaces its own binary with the verified build', async () => {
        const result = await runHog(['upgrade'], { env: AGENT, build: RUNNING, respond: release(NEWER) })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ action: 'upgraded', current: '0.1.0-alpha.5', latest: '0.1.0-alpha.8' })
        expect(result.executables['/usr/local/bin/hog']).toEqual(BINARY)
    })

    test('leaves the binary alone when the archive does not match its checksum', async () => {
        const tampered = new Uint8Array(ARCHIVE)
        tampered.set([tampered.at(-1)! ^ 0xff], tampered.length - 1)

        const result = await runHog(['upgrade'], { env: AGENT, build: RUNNING, respond: release(NEWER, tampered) })

        expect(result.error()).toMatchObject({ code: 'checksum_mismatch' })
        expect(result.executables).toEqual({})
    })

    test('installs the version --version names', async () => {
        const pinned = manifest('0.1.0-alpha.2', '2025-12-01T00:00:00Z')

        const result = await runHog(['upgrade', '--version', 'v0.1.0-alpha.2'], {
            env: AGENT,
            build: RUNNING,
            respond: release(pinned),
        })

        expect(result.requests.map((request) => request.url)).toContain(
            'https://releases.posthog.com/hog/v0.1.0-alpha.2/manifest.json'
        )
        expect(result.json()).toMatchObject({ action: 'upgraded', latest: '0.1.0-alpha.2' })
    })

    test.each([
        ['an agent gets the package manager command and hog runs nothing', AGENT, [], 'run_command', []],
        ['a person who says yes runs it', { NO_COLOR: '1' }, ['yes'], 'ran', [['brew', 'upgrade', 'hog']]],
        ['a person who says no runs nothing', { NO_COLOR: '1' }, ['no'], 'declined', []],
    ])('Homebrew: %s', async (_name, env, answers, action, commands) => {
        const result = await runHog(['upgrade', '--raw'], {
            env,
            stdoutIsTTY: env !== AGENT,
            answers,
            build: RUNNING,
            execPath: '/opt/homebrew/Cellar/hog/0.1.0/bin/hog',
            respond: release(NEWER),
        })

        expect(result.commands).toEqual(commands)
        expect(result.executables).toEqual({})
        expect(result.json()).toMatchObject({ action, command: 'brew upgrade hog' })
    })

    test.each([
        ['/home/test/.npm/_npx/1a2b/node_modules/@posthog/hog-linux-x64/bin/hog', 'npx'],
        ['/work/app/node_modules/@posthog/hog-linux-x64/bin/hog', 'project'],
    ])('runs nothing for a copy in %s', async (execPath) => {
        const result = await runHog(['upgrade'], { ...PERSON, answers: [], execPath, respond: release(NEWER) })

        expect(result.exitCode).toBe(0)
        expect(result.commands).toEqual([])
        expect(result.executables).toEqual({})
    })

    test('says so when hog is the latest version', async () => {
        const result = await runHog(['upgrade'], { ...PERSON, respond: release(manifest('0.1.0-alpha.5', BUILT)) })

        expect(result.stdout).toContain('hog 0.1.0-alpha.5 is the latest version')
        expect(result.executables).toEqual({})
    })
})
