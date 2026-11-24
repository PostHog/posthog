import { describe, expect, test } from 'bun:test'

import { readJson, runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

import type { Manifest } from './manifest'
import { API_NOTICE_HEADER, appliesTo, NoticeList, type Notice } from './notices'

const LATEST = 'https://releases.posthog.com/hog/latest/manifest.json'
const TELEMETRY = 'https://us.i.posthog.com/batch/'
const BUILT = '2026-01-01T00:00:00.000Z'
const RUNNING = { version: '1.2.0', date: BUILT }
const BREW = '/opt/homebrew/Cellar/hog/1.2.0/bin/hog'
const PERSON = { env: { NO_COLOR: '1' }, stdoutIsTTY: true, build: RUNNING, execPath: BREW }

const RETIRING: Notice = {
    id: 'hog-1-retiring',
    level: 'warning',
    message: 'hog 1 gets no more fixes after June 1, 2027. Move to hog 2.',
    url: 'https://posthog.com/docs/cli/migrating',
    below: '2.0.0',
    upgrade: true,
}

function release(notices: unknown[]): FakeRuntimeOptions['respond'] {
    const manifest = {
        schema: 1,
        name: 'hog',
        version: '1.2.0',
        tag: 'hog/v1.2.0',
        publishedAt: BUILT,
        buildDate: BUILT,
        baseUrl: 'https://releases.posthog.com/hog/v1.2.0/',
        mirrorUrl: 'https://github.com/PostHog/posthog/releases/download/hog/v1.2.0/',
        artifacts: {},
        notices,
    } satisfies Omit<Manifest, 'notices'> & { notices: unknown[] }
    return (url) => (url === LATEST ? { status: 200, body: manifest } : { status: 200, body: {} })
}

describe('which hogs a notice is for', () => {
    const hog = { version: '1.2.0', install: 'homebrew' as const, now: Date.parse('2026-06-01T00:00:00Z') }

    test.each<[string, Partial<Notice>, boolean]>([
        ['every version', {}, true],
        ['below the next major', { below: '2.0.0' }, true],
        ['below this version', { below: '1.2.0' }, false],
        ['from this version', { from: '1.2.0' }, true],
        ['from a later version', { from: '1.3.0' }, false],
        ['a range around this version', { from: '1.0.0', below: '1.3.0' }, true],
        ['before it ends', { until: '2026-06-02T00:00:00Z' }, true],
        ['once it ended', { until: '2026-06-01T00:00:00Z' }, false],
        ['this install kind', { installs: ['homebrew', 'script'] }, true],
        ['another install kind', { installs: ['npm-global'] }, false],
    ])('%s: %p', (_name, fields, expected) => {
        expect(appliesTo({ id: 'n', level: 'info', message: 'm', ...fields }, hog)).toBe(expected)
    })

    test('a version hog cannot read gets only the notices for every version', () => {
        const source = { ...hog, version: 'dev' }

        expect(appliesTo({ id: 'n', level: 'info', message: 'm' }, source)).toBe(true)
        expect(appliesTo({ id: 'n', level: 'info', message: 'm', below: '2.0.0' }, source)).toBe(false)
    })
})

describe('reading notices', () => {
    test.each([
        ['a level this hog does not know', { level: 'critical' }],
        ['a page outside posthog.com', { url: 'https://example.com/docs' }],
        ['a lookalike domain', { url: 'https://posthog.com.example.com/docs' }],
        ['a page over plain HTTP', { url: 'http://posthog.com/docs' }],
        ['a message over 300 characters', { message: 'x'.repeat(301) }],
        ['an empty message', { message: ' \u001b ' }],
        ['an id with spaces', { id: 'not an id' }],
        ['a version that is not semver', { below: 'two' }],
    ])('leaves out a notice with %s and keeps the others', (_name, fields) => {
        expect(NoticeList.parse([{ ...RETIRING, id: 'bad', ...fields }, RETIRING])).toEqual([RETIRING])
    })

    test('turns control characters and bidirectional overrides into spaces', () => {
        const [notice] = NoticeList.parse([{ ...RETIRING, message: 'Move\u001b[31m to\nhog‮ 2.\u0007' }])

        expect(notice?.message).toBe('Move [31m to hog 2.')
    })

    test('a notices field that is not a list leaves the manifest readable', () => {
        expect(NoticeList.parse('soon')).toEqual([])
    })
})

describe('showing notices', () => {
    test.each<[string, FakeRuntimeOptions, string]>([
        [
            'a person, as one line with the command for their install',
            PERSON,
            'Warning: hog 1 gets no more fixes after June 1, 2027. Move to hog 2. Run `brew upgrade hog`. https://posthog.com/docs/cli/migrating\n',
        ],
        [
            'a GitHub Actions job, as an annotation next to the JSON line',
            { env: { GITHUB_ACTIONS: 'true', CI: 'true' }, build: RUNNING, execPath: BREW },
            '{"notice":{"id":"hog-1-retiring","level":"warning","message":"hog 1 gets no more fixes after June 1, 2027. Move to hog 2.","url":"https://posthog.com/docs/cli/migrating","command":"brew upgrade hog"}}\n' +
                '::warning title=hog::hog 1 gets no more fixes after June 1, 2027. Move to hog 2. Run `brew upgrade hog`. https://posthog.com/docs/cli/migrating\n',
        ],
    ])('shows a warning to %s', async (_name, options, stderr) => {
        const other: Notice = { ...RETIRING, id: 'hog-3-retiring', from: '3.0.0', below: undefined }

        const result = await runHog(['config', 'schema'], { ...options, respond: release([RETIRING, other]) })

        expect(result.stderr).toBe(stderr)
    })

    test('gives an agent the notice as JSON, without an annotation', async () => {
        const result = await runHog(['config', 'schema'], {
            env: { CLAUDECODE: '1', GITHUB_ACTIONS: 'true' },
            build: RUNNING,
            execPath: BREW,
            respond: release([RETIRING]),
        })

        expect(readJson(result.stderr)).toEqual({
            notice: {
                id: 'hog-1-retiring',
                level: 'warning',
                message: 'hog 1 gets no more fixes after June 1, 2027. Move to hog 2.',
                url: 'https://posthog.com/docs/cli/migrating',
                command: 'brew upgrade hog',
            },
        })
    })

    test('shows an info notice once a day and a warning on every command', async () => {
        const info: Notice = { id: 'hog-2-out', level: 'info', message: 'hog 2 is out.' }
        const respond = release([RETIRING, info])

        const first = await runHog(['config', 'schema'], { ...PERSON, respond })
        const second = await runHog(['config', 'schema'], { ...PERSON, files: first.files, respond })

        expect(first.stderr).toContain('Notice: hog 2 is out.')
        expect(second.stderr).not.toContain('hog 2 is out')
        expect(second.stderr).toContain('Warning: hog 1 gets no more fixes')
    })

    test('counts each notice it shows', async () => {
        const result = await runHog(['config', 'schema'], {
            ...PERSON,
            telemetryToken: 'phc_test',
            respond: release([RETIRING]),
        })

        const batch = result.requests
            .filter((request) => request.url === TELEMETRY)
            .flatMap((request: any) => request.body.batch)
        expect(batch).toContainEqual(
            expect.objectContaining({
                event: 'cli notice shown',
                properties: expect.objectContaining({
                    notice_id: 'hog-1-retiring',
                    notice_level: 'warning',
                    notice_channel: 'manifest',
                    annotated: false,
                }),
            })
        )
    })
})

describe('notices from the PostHog API', () => {
    const QUERY = ['endpoints', 'run', 'by-type']

    function api(header: string, manifest: unknown[] = []): FakeRuntimeOptions['respond'] {
        const releases = release(manifest)!
        return (url, body, authorization, headers) =>
            url === LATEST
                ? releases(url, body, authorization, headers)
                : { status: 200, body: { columns: ['n'], results: [[1]] }, headers: { [API_NOTICE_HEADER]: header } }
    }

    test('shows a notice the API sends, also with update checks off', async () => {
        const result = await runHog(QUERY, {
            ...PERSON,
            env: { ...TEST_CREDENTIALS, NO_COLOR: '1', HOG_NO_UPDATE_CHECK: '1' },
            respond: api(JSON.stringify([RETIRING])),
        })

        expect(result.exitCode).toBe(0)
        expect(result.stderr).toContain(
            'Warning: hog 1 gets no more fixes after June 1, 2027. Move to hog 2. Run `brew upgrade hog`.'
        )
        expect(result.requests.filter((request) => request.url === LATEST)).toEqual([])
    })

    test('shows a notice the API and the manifest both send once', async () => {
        const result = await runHog(QUERY, {
            ...PERSON,
            env: { ...TEST_CREDENTIALS, NO_COLOR: '1' },
            respond: api(JSON.stringify([RETIRING]), [RETIRING]),
        })

        expect(result.stderr.match(/hog 1 gets no more fixes/g)).toHaveLength(1)
    })

    test.each([
        ['not JSON', 'soon'],
        ['a notice that links away', JSON.stringify([{ ...RETIRING, url: 'https://example.com' }])],
    ])('ignores a header that is %s, and the command still works', async (_name, header) => {
        const result = await runHog(QUERY, {
            ...PERSON,
            env: { ...TEST_CREDENTIALS, NO_COLOR: '1', HOG_NO_UPDATE_CHECK: '1' },
            respond: api(header),
        })

        expect(result.exitCode).toBe(0)
        expect(result.stderr).toBe('')
    })
})
