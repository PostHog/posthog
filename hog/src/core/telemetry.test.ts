import { describe, expect, test } from 'bun:test'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { runHog, TEST_CREDENTIALS, type HogRun } from '@/testing'

import { SMALL_MAPPING } from '../../test/parity/fixtures'
import { detectCi } from './telemetry'

const TELEMETRY = 'https://us.i.posthog.com/batch/'
const ON = { telemetryToken: 'phc_test' }
const AGENT = { ...TEST_CREDENTIALS, CLAUDECODE: '1' }

function events(
    result: HogRun
): { event: string; distinct_id: string; timestamp: string; properties: Record<string, any> }[] {
    return result.requests.filter((request) => request.url === TELEMETRY).flatMap((request: any) => request.body.batch)
}

describe('telemetry', () => {
    test('a command sends one usage event with option names and no values', async () => {
        const result = await runHog(['endpoints', 'run', 'by-type', '--var', 'secret=hunter2'], {
            ...ON,
            env: AGENT,
            respond: (url) =>
                url === TELEMETRY
                    ? { status: 200, body: {} }
                    : { status: 200, body: { columns: ['n'], results: [[1]] } },
        })
        expect(events(result)).toEqual([
            {
                event: 'posthog cli command run',
                distinct_id: expect.any(String),
                timestamp: expect.any(String),
                properties: expect.objectContaining({
                    command_name: 'endpoints_run',
                    command_path: 'endpoints run',
                    success: true,
                    exit_code: 0,
                    options: ['var'],
                    source: 'endpoint',
                    variable_count: 1,
                    env_id: null,
                    agent: 'claude-code',
                    $process_person_profile: false,
                }),
            },
        ])
        expect(JSON.stringify(result.requests.filter((request) => request.url === TELEMETRY))).not.toContain('hunter2')
    })

    test.each([
        ['a query that starts with dashes', ['query', 'run', '--secret-customer query']],
        ['a value that starts with dashes', ['et', 'release', '--release-version', '--secret-customer']],
    ])('%s never reaches telemetry', async (_name, argv) => {
        const result = await runHog(argv, { ...ON, env: AGENT, respond: () => ({ status: 200, body: {} }) })
        expect(events(result).length).toBeGreaterThan(0)
        expect(JSON.stringify(events(result))).not.toContain('secret-customer')
    })

    test.each([
        ['with no identity cache', {}],
        // A broken cache must not fail the command.
        ['with a cache that is not an object', { '/home/test/.posthog/hog-telemetry-identity.json': 'null' }],
    ])(
        'a PostHog Cloud key ties events to its user and groups, and hog looks them up once, %s',
        async (_name, files) => {
            const cloud = { ...AGENT, HOG_HOST: 'https://us.posthog.com' }
            const respond = (url: string): { status: number; body: unknown } =>
                url.endsWith('/api/users/@me/')
                    ? { status: 200, body: { distinct_id: 'user-1', organization: { id: 'org-current' } } }
                    : url.endsWith('/api/projects/7/')
                      ? { status: 200, body: { uuid: 'project-uuid', organization: 'org-1' } }
                      : { status: 200, body: {} }
            const first = await runHog(['commands'], { ...ON, env: cloud, respond, files })
            const second = await runHog(['commands'], { ...ON, env: cloud, respond, files: first.files })

            for (const result of [first, second]) {
                const [event] = events(result)
                expect(event!.distinct_id).toBe('user-1')
                expect(event!.properties).toMatchObject({
                    env_id: '7',
                    $groups: { organization: 'org-1', project: 'project-uuid' },
                })
                expect(event!.properties).not.toHaveProperty('$process_person_profile')
            }
            expect(second.requests.filter((request) => request.url !== TELEMETRY)).toEqual([])
        }
    )

    test.each([
        [
            'a GitHub-hosted job',
            { GITHUB_ACTIONS: 'true', RUNNER_ENVIRONMENT: 'github-hosted' },
            'github-actions',
            'github-hosted',
        ],
        [
            'a Blacksmith runner',
            { GITHUB_ACTIONS: 'true', RUNNER_ENVIRONMENT: 'self-hosted', BLACKSMITH_VM_ID: 'vm' },
            'github-actions',
            'blacksmith',
        ],
        ['a Depot runner', { GITHUB_ACTIONS: 'true', RUNNER_NAME: 'depot-abc123' }, 'github-actions', 'depot'],
        [
            'Depot CI, which looks like GitHub Actions too',
            { DEPOT_JOB_URL: 'https://depot.dev/x', GITHUB_ACTIONS: 'true' },
            'depot-ci',
            null,
        ],
        ['Harness, which also sets Drone variables', { HARNESS_BUILD_ID: '1', DRONE: 'true' }, 'harness', null],
        ['a Vercel build', { VERCEL: '1', CI: '1' }, 'vercel', null],
        ['a Vercel function, which is not CI', { VERCEL: '1' }, null, null],
        ['Cloudflare Workers Builds', { WORKERS_CI: '1' }, 'cloudflare-workers', null],
    ])('detects %s', (_name, env, provider, runner) => {
        expect(detectCi(env)).toEqual({ provider, runner })
    })

    test('the install ID stays the same across runs', async () => {
        const first = await runHog(['commands'], { ...ON, env: AGENT })
        const second = await runHog(['commands'], { ...ON, env: AGENT, files: first.files })
        expect(events(second)[0]!.distinct_id).toBe(events(first)[0]!.distinct_id)
        expect(first.files['/home/test/.posthog/hog-telemetry-id']).toBe(`${events(first)[0]!.distinct_id}\n`)
    })

    test.each([
        ['HOG_NO_TELEMETRY', ['commands'], { HOG_NO_TELEMETRY: '1' }, {}],
        ['DO_NOT_TRACK', ['commands'], { DO_NOT_TRACK: '1' }, {}],
        ['--no-telemetry', ['commands', '--no-telemetry'], {}, {}],
        ['--no-telemetry on a usage error', ['nope', '--no-telemetry'], {}, {}],
        ['cli.telemetry in posthog.json', ['commands'], {}, { '/work/posthog.json': '{"cli":{"telemetry":false}}' }],
        ['cli.telemetry on a usage error', ['nope'], {}, { '/work/posthog.json': '{"cli":{"telemetry":false}}' }],
        [
            'cli.telemetry in a posthog.json with an unknown key',
            ['commands'],
            {},
            { '/work/posthog.json': '{"cli":{"telemetry":false},"newerSetting":1}' },
        ],
        ['DO_NOT_TRACK with a value hog does not know', ['commands'], { DO_NOT_TRACK: 'please' }, {}],
    ])('%s turns telemetry off', async (_name, argv, env, files) => {
        const result = await runHog(argv, { ...ON, env: { ...AGENT, ...env }, files })
        expect(events(result)).toEqual([])
        expect(result.files['/home/test/.posthog/hog-telemetry-id']).toBeUndefined()
    })

    test.each([
        ['a missing endpoint', 404, 'not_found', 'hog:endpoints get:not_found:404'],
        ['a key without the scope', 403, 'permission_denied', 'hog:endpoints get:permission_denied:403'],
    ])('%s sends its code and status, never the message', async (_name, status, code, fingerprint) => {
        const result = await runHog(['endpoints', 'get', 'missing'], {
            ...ON,
            env: AGENT,
            respond: (url) =>
                url === TELEMETRY
                    ? { status: 200, body: {} }
                    : { status, body: { type: 'invalid_request', code, detail: 'Private detail /Users/me/app' } },
        })

        const [exception, run] = events(result)
        expect(exception!.properties).toMatchObject({
            $exception_list: [{ type: code, value: code }],
            $exception_fingerprint: fingerprint,
            http_status: status,
        })
        expect(JSON.stringify(events(result))).not.toContain('Private detail')
        expect(run!.properties).toMatchObject({ success: false, error_code: code, exit_code: 1 })
    })

    test('a posthog.json hog cannot parse stops the command, and telemetry still reports it', async () => {
        const result = await runHog(['endpoints', 'list'], {
            ...ON,
            env: AGENT,
            files: { '/work/posthog.json': '{"cli":' },
            respond: () => ({ status: 200, body: {} }),
        })
        expect(result.exitCode).toBe(1)
        expect(events(result).map((event) => [event.event, event.properties.error_code])).toEqual([
            ['$exception', 'invalid_config'],
            ['posthog cli command run', 'invalid_config'],
        ])
    })

    test('an upload sends the posthog-cli upload events', async () => {
        const folder = mkdtempSync(join(tmpdir(), 'hog-telemetry-'))
        writeFileSync(join(folder, 'mapping.txt'), SMALL_MAPPING)
        const result = await runHog(
            ['et', 'upload', 'mapping.txt', '--map-id', 'map-1', '--release-name', 'app', '--release-version', '1'],
            {
                ...ON,
                env: AGENT,
                cwd: folder,
                useDisk: true,
                respond: (url) => {
                    if (url.includes('/releases/hash/')) {
                        return { status: 200, body: { id: 'release-1', hash_id: 'h', version: '1', project: 'app' } }
                    }
                    return url.endsWith('/bulk_check_upload/')
                        ? { status: 200, body: { chunk_ids_to_upload: [] } }
                        : { status: 200, body: {} }
                },
            }
        )
        expect(result.exitCode).toBe(0)
        const uploads = events(result).filter((event) => event.event.startsWith('error_tracking_cli'))
        expect(uploads.map((event) => [event.event, event.properties.type, event.properties.file_count])).toEqual([
            ['error_tracking_cli_sourcemaps_upload_started', 'proguard', 1],
            ['error_tracking_cli_sourcemaps_upload_finished', 'proguard', 1],
        ])
        expect(uploads[1]!.properties).toMatchObject({ success: true, skipped_already_present: 1, uploaded: 0 })
    })
})
