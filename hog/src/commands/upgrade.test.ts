import { describe, expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { readJson, runHog, type FakeRuntimeOptions } from '@/testing'
import { extractFile } from '@/updates/archive'
import type { Manifest } from '@/updates/manifest'

const LATEST = 'https://releases.posthog.com/hog/latest/manifest.json'
const AGENT = { CLAUDECODE: '1' }
// The fake clock starts on 2026-01-01.
const BUILT = '2025-12-20T00:00:00.000Z'
const RUNNING = { version: '0.1.0-alpha.5', date: BUILT }

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
        publishedAt,
        buildDate: publishedAt,
        baseUrl: `https://releases.posthog.com/hog/v${version}/`,
        mirrorUrl: `https://github.com/PostHog/posthog/releases/download/hog/v${version}/`,
        artifacts: { 'linux-x64': { file: 'hog-linux-x64.tar.gz', sha256: ARCHIVE_SHA, size: ARCHIVE.length } },
        ...extra,
    }
}

function release(latest: Manifest | null, archive: Uint8Array = ARCHIVE): FakeRuntimeOptions['respond'] {
    return (url) => {
        if (latest && (url === LATEST || url.endsWith(`/v${latest.version}/manifest.json`))) {
            return { status: 200, body: latest }
        }
        if (latest && url === `${latest.baseUrl}hog-linux-x64.tar.gz`) {
            return { status: 200, body: archive }
        }
        return { status: 500, body: {} }
    }
}

const NPM_PATH = '/home/test/.nvm/versions/node/v22.0.0/lib/node_modules/@posthog/hog-linux-x64/bin/hog'

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

    test('auth status without a home folder still reports the release, from one manifest request', async () => {
        const result = await runHog(['auth', 'status'], {
            env: { ...AGENT, HOG_PERSONAL_API_KEY: 'phx_test', HOG_PROJECT_ID: '42' },
            build: RUNNING,
            noHome: true,
            respond: (url) =>
                url === LATEST
                    ? { status: 200, body: manifest('0.2.0', BUILT) }
                    : url.endsWith('/api/users/@me/')
                      ? { status: 200, body: { email: 'test@example.com' } }
                      : { status: 200, body: { id: 42, name: 'Test project' } },
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ authenticated: true, hog: { latest: '0.2.0', updateAvailable: true } })
        expect(result.requests.filter((request) => request.url === LATEST)).toHaveLength(1)
    })

    test('waits an hour after a failed check before it asks again', async () => {
        const failed = await runHog(['config', 'schema'], { ...PERSON, respond: release(null) })

        const next = await runHog(['config', 'schema'], {
            ...PERSON,
            files: failed.files,
            respond: release(manifest('0.2.0', BUILT)),
        })

        expect(failed.requests.filter((request) => request.url === LATEST)).toHaveLength(1)
        expect(next.requests.filter((request) => request.url === LATEST)).toHaveLength(0)
    })

    test.each([
        ['--skip-ssl-verification', { ...PERSON }, ['--skip-ssl-verification']],
        ['HOG_SKIP_SSL_VERIFICATION', { ...PERSON, env: { NO_COLOR: '1', HOG_SKIP_SSL_VERIFICATION: '1' } }, []],
    ])('%s sends no update request, because the manifest could not be trusted', async (_name, options, flags) => {
        const result = await runHog(['config', 'schema', ...flags], {
            ...options,
            respond: release(manifest('0.3.0', BUILT)),
        })

        expect(result.requests.filter((request) => request.url.includes('releases.posthog.com'))).toEqual([])
    })

    test('keeps a failed JSON command to one error object on stderr, without the minimumVersion warning', async () => {
        const latest = manifest('0.1.0-alpha.7', BUILT, { minimumVersion: '0.1.0-alpha.6' })

        const result = await runHog(['setup', 'bogus'], { env: AGENT, build: RUNNING, respond: release(latest) })

        expect(result.exitCode).toBe(2)
        expect(result.error()).toMatchObject({ code: 'invalid_setup_command' })
        expect(result.stderr.trim().split('\n')).toHaveLength(1)
    })

    test('reads the release at most once a day', async () => {
        const first = await runHog(['config', 'schema'], { ...PERSON, respond: release(manifest('0.2.0', BUILT)) })

        const second = await runHog(['config', 'schema'], { ...PERSON, files: first.files, respond: release(null) })

        expect(first.requests.filter((request) => request.url === LATEST)).toHaveLength(1)
        expect(second.requests.filter((request) => request.url === LATEST)).toHaveLength(0)
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
        ['npm', NPM_PATH, 'Run `npm install -g @posthog/hog@latest`, then run `hog setup` again.'],
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

    test.each([
        ['an npm install carries on, because npm may not have it yet', NPM_PATH, 0],
        ['a standalone binary stops, because the release bucket has it', '/usr/local/bin/hog', 1],
    ])('a release out for an hour: %s', async (_name, execPath, exitCode) => {
        const result = await runHog(['setup'], {
            env: AGENT,
            build: RUNNING,
            execPath,
            respond: release(manifest('0.1.0-alpha.6', '2025-12-31T23:00:00Z')),
        })

        expect(result.exitCode).toBe(exitCode)
    })

    test('says to update once, without the notice after the error', async () => {
        const result = await runHog(['setup'], { ...PERSON, respond: release(manifest('0.2.0', BUILT)) })

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain('Setup needs the latest hog, 0.2.0')
        expect(result.stderr).not.toContain('is out')
    })

    test('ignores an old cached release when the manifest is out of reach', async () => {
        const twoDaysAgo = Date.UTC(2026, 0, 1) - 2 * 24 * 60 * 60 * 1000
        const cache = { checkedAt: twoDaysAgo, latest: { version: '0.2.0', publishedAt: BUILT } }

        const result = await runHog(['setup'], {
            env: AGENT,
            build: RUNNING,
            files: { '/home/test/.config/hog/update-check.json': JSON.stringify(cache) },
            respond: release(null),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ step: 'purpose', hog: { latest: null } })
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
        expect(result.requests.filter((request) => request.url === LATEST)).toHaveLength(0)
    })
})

describe('hog upgrade', () => {
    const NEWER = manifest('0.1.0-alpha.8', '2025-12-30T00:00:00Z')

    test.each([
        ['/opt/homebrew/Cellar/hog/0.1.0/bin/hog', 'homebrew'],
        [NPM_PATH, 'npm-global'],
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

    const TAMPERED = new Uint8Array(ARCHIVE)
    TAMPERED.set([TAMPERED.at(-1)! ^ 0xff], TAMPERED.length - 1)
    const SIZE_OFF = {
        artifacts: { 'linux-x64': { file: 'hog-linux-x64.tar.gz', sha256: ARCHIVE_SHA, size: ARCHIVE.length - 1 } },
    }

    test.each([
        ['its checksum', NEWER, TAMPERED],
        ['its size', manifest(NEWER.version, NEWER.publishedAt, SIZE_OFF), ARCHIVE],
    ])('leaves the binary alone when the archive does not match %s', async (_name, latest, archive) => {
        const result = await runHog(['upgrade'], { env: AGENT, build: RUNNING, respond: release(latest, archive) })

        expect(result.error()).toMatchObject({ code: 'checksum_mismatch' })
        expect(result.executables).toEqual({})
    })

    const elsewhere = (baseUrl: string): Partial<Manifest> => ({ baseUrl })

    test.each([
        ['another host', elsewhere('https://releases.example.com/hog/v0.1.0-alpha.8/'), 'untrusted_release_url'],
        ['a look-alike host', elsewhere('https://releases.posthog.com.example.com/hog/'), 'untrusted_release_url'],
        [
            'a path out of the release folder',
            elsewhere('https://releases.posthog.com/hog/../x/'),
            'untrusted_release_url',
        ],
        [
            'another GitHub repository',
            { mirrorUrl: 'https://github.com/example/posthog/releases/download/hog/v0.1.0-alpha.8/' },
            'untrusted_release_url',
        ],
        [
            'an archive larger than any build',
            { artifacts: { 'linux-x64': { file: 'hog-linux-x64.tar.gz', sha256: ARCHIVE_SHA, size: 2 ** 40 } } },
            'invalid_release_manifest',
        ],
    ])('downloads nothing when the manifest names %s', async (_name, extra, code) => {
        const latest = manifest('0.1.0-alpha.8', '2025-12-30T00:00:00Z', extra)

        const result = await runHog(['upgrade'], { env: AGENT, build: RUNNING, respond: release(latest) })

        expect(result.error()).toMatchObject({ code })
        expect(result.requests.filter((request) => request.url.endsWith('.tar.gz'))).toEqual([])
        expect(result.executables).toEqual({})
    })

    test.each([
        ['trusts an https release folder', 'https://hog-mirror.example.com/releases', { action: 'upgraded' }, 1],
        ['refuses a plain http one', 'http://hog-mirror.example.com/releases', { code: 'untrusted_release_url' }, 0],
    ])('HOG_RELEASES_URL: %s', async (_name, mirror, expected, replaced) => {
        const latest = manifest('0.1.0-alpha.8', '2025-12-30T00:00:00Z', elsewhere(`${mirror}/v0.1.0-alpha.8/`))

        const result = await runHog(['upgrade'], {
            env: { ...AGENT, HOG_RELEASES_URL: mirror },
            build: RUNNING,
            respond: (url) =>
                url === `${mirror}/latest/manifest.json`
                    ? { status: 200, body: latest }
                    : url === `${latest.baseUrl}hog-linux-x64.tar.gz`
                      ? { status: 200, body: ARCHIVE }
                      : { status: 500, body: {} },
        })

        expect(result.exitCode === 0 ? result.json() : result.error()).toMatchObject(expected)
        expect(Object.keys(result.executables)).toHaveLength(replaced)
    })

    test('refuses an archive that unpacks to more than the limit', () => {
        expect(() => extractFile(ARCHIVE, 'hog-linux-x64.tar.gz', 'hog', 512)).toThrow(
            'it unpacks to more than 512 bytes'
        )
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

    const BREW = { build: RUNNING, execPath: '/opt/homebrew/Cellar/hog/0.1.0/bin/hog', respond: release(NEWER) }

    test.each([
        ['an agent', ['upgrade'], { ...BREW, env: AGENT }],
        ['a person with --raw, so stdout stays JSON', ['upgrade', '--raw'], { ...PERSON, ...BREW, answers: [] }],
    ])('Homebrew: %s gets the command and hog runs nothing', async (_name, argv, options) => {
        const result = await runHog(argv, options)

        expect(result.commands).toEqual([])
        expect(result.json()).toMatchObject({ action: 'run_command', command: 'brew upgrade hog' })
    })

    test.each([
        ['says yes runs it', ['yes'], 'Updated hog to 0.1.0-alpha.8', [['brew', 'upgrade', 'hog']]],
        ['says no runs nothing', ['no'], 'Homebrew manages this copy', []],
    ])('Homebrew: a person who %s', async (_name, answers, stdout, commands) => {
        const result = await runHog(['upgrade'], { ...PERSON, ...BREW, answers })

        expect(result.commands).toEqual(commands)
        expect(result.executables).toEqual({})
        expect(result.stdout).toContain(stdout)
    })

    test('refuses a version pin for Homebrew, which installs only the latest', async () => {
        const result = await runHog(['upgrade', '--version', '0.1.0-alpha.2'], { ...BREW, env: AGENT })

        expect(result.error()).toMatchObject({ code: 'version_pin_unsupported' })
        expect(result.requests.filter((request) => request.url.includes('releases.posthog.com'))).toEqual([])
    })

    test('refuses to run with TLS verification off, and sends no request', async () => {
        const result = await runHog(['upgrade'], {
            env: { ...AGENT, HOG_SKIP_SSL_VERIFICATION: '1' },
            build: RUNNING,
            respond: release(NEWER),
        })

        expect(result.error()).toMatchObject({ code: 'upgrade_needs_tls' })
        expect(result.requests.filter((request) => request.url.includes('releases.posthog.com'))).toEqual([])
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
