import { afterAll, describe, expect, mock, test } from 'bun:test'
import { z } from 'zod'

import * as providers from '@/ci/providers/registry'
import { FAKE_WORKLOAD_PROVIDER, readJson, runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

mock.module('@/ci/providers/registry', () => ({ ...providers, WORKLOAD_PROVIDERS: [FAKE_WORKLOAD_PROVIDER] }))
afterAll(() => {
    mock.module('@/ci/providers/registry', () => providers)
})

const HOST = TEST_CREDENTIALS.HOG_HOST
const REQUESTS = `${HOST}/api/projects/7/workload_trust_policy_requests/`
const PENDING_FILE = '/home/test/.config/hog/pending-ci-setup.json'
const REPOSITORY = {
    '/work/.git/config': '[core]\n\tbare = false\n[remote "origin"]\n\turl = git@ci.example.com:acme/web.git\n',
    '/work/.fake-ci.yml': 'jobs: {}\n',
}
const CREATED = {
    id: 'req-1',
    status: 'pending',
    approval_url: `${HOST}/project/7/workload-trust-policy-requests/req-1`,
    can_approve: false,
    approvers: ['Olive Owner'],
    expires_at: '2026-01-08T00:00:00Z',
    policy_id: null,
}

const PROVIDERS = {
    supported: [
        {
            key: 'fake_ci',
            name: 'Fake CI',
            issuer: 'https://ci.example.com',
            docs_url: 'https://example.com/docs/fake-ci',
            condition_presets: [
                {
                    key: 'branch_push',
                    label: 'Pushes to a branch',
                    help_text: 'Runs for commits pushed to this branch.',
                    conditions: { event_name: 'push', ref: 'refs/heads/{value}' },
                    takes_value: true,
                    placeholder: 'main',
                    default_value: 'main',
                },
                {
                    key: 'environment',
                    label: 'A deployment environment',
                    help_text: 'Jobs that deploy to this environment.',
                    conditions: { environment: '{value}' },
                    takes_value: true,
                    placeholder: 'production',
                    default_value: '',
                },
            ],
            setup_snippet: 'fake-ci:\n  oidc: true',
        },
    ],
}

// Like Depot CI: every policy pins an organization.
const ORG_PROVIDERS = {
    supported: [
        {
            ...PROVIDERS.supported[0],
            condition_presets: [
                {
                    key: 'organization',
                    label: 'Your organization',
                    help_text: 'Every policy pins your organization.',
                    conditions: { org_id: '{value}', forge: 'github' },
                    takes_value: true,
                    placeholder: 'org123',
                    default_value: '',
                },
                ...PROVIDERS.supported[0]!.condition_presets,
            ],
            required_presets: ['organization'],
        },
    ],
}

// The request API: providers, a lookup, a new request, then `pendingPolls` answers of "still pending" before `final`.
function policyApi(options: { canApprove?: boolean; pendingPolls?: number; final?: string; providers?: unknown } = {}) {
    let polls = 0
    const created = { ...CREATED, can_approve: options.canApprove ?? false }
    return (url: string): { status: number; body: unknown } => {
        if (url === `${REQUESTS}providers/`) {
            return { status: 200, body: options.providers ?? PROVIDERS }
        }
        if (url.startsWith(`${REQUESTS}resolve_subject/`)) {
            return { status: 200, body: { subject: '123', subject_name: 'Acme/Web', found_via: 'Fake CI' } }
        }
        if (url === REQUESTS) {
            return { status: 201, body: created }
        }
        if (url === `${REQUESTS}req-1/`) {
            const status = polls++ < (options.pendingPolls ?? 0) ? 'pending' : (options.final ?? 'approved')
            return { status: 200, body: { ...created, status, policy_id: status === 'approved' ? 'pol-1' : null } }
        }
        return { status: 404, body: { detail: 'Not found.' } }
    }
}

function setup(args: string[], options: FakeRuntimeOptions): ReturnType<typeof runHog> {
    return runHog(['ci', 'setup', ...args], { env: TEST_CREDENTIALS, files: REPOSITORY, ...options })
}

describe('hog ci setup', () => {
    test('asks for a policy for the repository it runs in, and hands an agent the link and the snippet', async () => {
        const run = await setup(
            ['--preset', 'branch_push=main', '--scope', 'query:read,error_tracking:write', '--scope', 'query:read'],
            {
                respond: policyApi(),
            }
        )

        expect(run.exitCode).toBe(0)
        expect(run.requests.find((request) => request.url === REQUESTS)?.body).toEqual({
            name: 'Acme/Web on Fake CI',
            issuer: 'https://ci.example.com',
            subject: '123',
            subject_name: 'Acme/Web',
            conditions: { event_name: 'push', ref: 'refs/heads/main' },
            scopes: ['error_tracking:write', 'query:read'],
        })
        expect(run.json()).toMatchObject({
            status: 'pending',
            url: CREATED.approval_url,
            approver: 'an organization admin',
            approverNames: ['Olive Owner'],
            instructions: expect.not.stringContaining('Olive'),
            next: 'hog ci setup --wait',
            posthogJson: { projectId: 7 },
            host: HOST,
        })
        expect(readJson(run.files[PENDING_FILE] ?? '{}')).toMatchObject({ requestId: 'req-1', provider: 'fake_ci' })
    })

    test.each([
        [
            'an admin waits at the terminal until they approve it',
            true,
            'Fake CI jobs can now use hog in this project',
            2,
        ],
        [
            'a member gets the link to send an admin and does not wait',
            false,
            'Only an organization admin (Olive Owner) can approve it',
            0,
        ],
    ])('%s', async (_name, canApprove, shown, polls) => {
        const run = await setup(['--preset', 'environment=production', '--scope', 'query:read'], {
            stdoutIsTTY: true,
            respond: policyApi({ canApprove, pendingPolls: 1 }),
        })

        expect(run.exitCode).toBe(0)
        expect(run.stdout).toContain(shown)
        expect(run.stdout).toContain('the job also needs HOG_HOST=https://ph.example.com')
        expect(run.requests.filter((request) => request.url === `${REQUESTS}req-1/`)).toHaveLength(polls)
        expect(PENDING_FILE in run.files).toBe(!canApprove)
    })

    test('--wait resumes the request an earlier run started and prints the snippet once approved', async () => {
        const first = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], { respond: policyApi() })
        const run = await runHog(['ci', 'setup', '--wait'], {
            env: TEST_CREDENTIALS,
            files: first.files,
            respond: policyApi({ pendingPolls: 2 }),
        })

        expect(run.exitCode).toBe(0)
        expect(run.json(z.object({ status: z.string(), policyId: z.string() }).loose())).toMatchObject({
            status: 'approved',
            policyId: 'pol-1',
        })
        expect(PENDING_FILE in run.files).toBe(false)
    })

    test.each([
        ['reuses the request while it waits for an admin', ['branch_push=main'], 'pending', 1],
        [
            'reuses the request when the presets come in another order',
            ['branch_push=main', 'environment=production'],
            'pending',
            1,
        ],
        ['starts a new request once an admin rejected the last one', ['branch_push=main'], 'rejected', 2],
        ['picks up the policy once an admin approved the last one', ['branch_push=main'], 'approved', 1],
    ])('running it again %s', async (_name, presets, lastStatus, created) => {
        const args = (order: string[]): string[] => [
            ...order.flatMap((preset) => ['--preset', preset]),
            '--scope',
            'query:read',
        ]
        const first = await setup(args(presets), { respond: policyApi() })
        const api = policyApi({ final: lastStatus })
        const run = await setup(args([...presets].reverse()), { files: first.files, respond: api })

        expect(run.exitCode).toBe(0)
        expect(run.requests.filter((request) => request.url === REQUESTS && request.method === 'POST')).toHaveLength(
            created - 1
        )
    })

    test('--wait after the deadline still picks up an approval that came in before it', async () => {
        const first = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], { respond: policyApi() })
        const pending = readJson(first.files[PENDING_FILE] ?? '{}', z.object({}).loose())
        const files = { ...first.files, [PENDING_FILE]: JSON.stringify({ ...pending, expiresAt: 0 }) }

        const run = await runHog(['ci', 'setup', '--wait'], { env: TEST_CREDENTIALS, files, respond: policyApi() })

        expect(run.exitCode).toBe(0)
        expect(PENDING_FILE in run.files).toBe(false)
    })

    test('--wait keeps the request when a gateway answers with an HTML error page', async () => {
        const first = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], { respond: policyApi() })
        const run = await runHog(['ci', 'setup', '--wait'], {
            env: TEST_CREDENTIALS,
            files: first.files,
            respond: () => ({ status: 502, body: '<html>Bad gateway</html>' }),
        })

        expect(run.error().code).toBe('policy_request_interrupted')
        expect(PENDING_FILE in run.files).toBe(true)
    })

    test('--wait keeps an approved request when the provider settings fail to load', async () => {
        const first = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], { respond: policyApi() })
        const run = await runHog(['ci', 'setup', '--wait'], {
            env: TEST_CREDENTIALS,
            files: first.files,
            respond: (url) =>
                url === `${REQUESTS}providers/` ? { status: 503, body: { detail: 'Unavailable.' } } : policyApi()(url),
        })

        expect(run.exitCode).not.toBe(0)
        expect(PENDING_FILE in run.files).toBe(true)
    })

    test('--wait gives up after a while and keeps the request for the next --wait', async () => {
        const first = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], { respond: policyApi() })
        const run = await runHog(['ci', 'setup', '--wait'], {
            env: TEST_CREDENTIALS,
            files: first.files,
            respond: policyApi({ pendingPolls: 1_000 }),
        })

        expect(run.error().code).toBe('policy_request_still_pending')
        expect(PENDING_FILE in run.files).toBe(true)
    })

    test.each([
        ['no scope', ['--preset', 'branch_push=main'], REPOSITORY, 'missing_scopes'],
        ['an unknown preset', ['--preset', 'tag=v1', '--scope', 'query:read'], REPOSITORY, 'unknown_preset'],
        [
            'a preset passed twice',
            ['--preset', 'branch_push=main', '--preset', 'branch_push=dev', '--scope', 'query:read'],
            REPOSITORY,
            'invalid_preset',
        ],
        [
            'a control character in a value',
            ['--preset', 'environment=prod\u001b', '--scope', 'query:read'],
            REPOSITORY,
            'invalid_preset',
        ],
        [
            'no origin remote',
            ['--provider', 'fake_ci', '--preset', 'branch_push=main', '--scope', 'query:read'],
            { ...REPOSITORY, '/work/.git/config': '[remote "upstream"]\n\turl = git@ci.example.com:acme/web.git\n' },
            'missing_repository',
        ],
        [
            'no CI config in the repository',
            ['--preset', 'branch_push=main', '--scope', 'query:read'],
            { '/work/.git/config': REPOSITORY['/work/.git/config'] },
            'provider_not_detected',
        ],
    ])('stops before asking PostHog when it has %s', async (_name, args, files, code) => {
        const run = await setup(args, { files, respond: policyApi() })

        expect(run.exitCode).not.toBe(0)
        expect(run.error().code).toBe(code)
        expect(run.requests.some((request) => request.url === REQUESTS)).toBe(false)
    })

    test("without a preset, an agent gets the choices with PostHog's explanations and nothing is requested", async () => {
        const run = await setup(['--scope', 'query:read'], { respond: policyApi() })

        expect(run.exitCode).toBe(0)
        expect(run.json()).toEqual({
            status: 'input_required',
            provider: 'Fake CI',
            values: [],
            presets: [
                {
                    option: '--preset branch_push=<value>',
                    label: 'Pushes to a branch',
                    help: 'Runs for commits pushed to this branch.',
                    example: 'main',
                },
                {
                    option: '--preset environment=<value>',
                    label: 'A deployment environment',
                    help: 'Jobs that deploy to this environment.',
                    example: 'production',
                },
            ],
            docsUrl: 'https://example.com/docs/fake-ci',
        })
        expect(run.requests.some((request) => request.url === REQUESTS)).toBe(false)
    })

    test('a person at the terminal picks a preset and types its value', async () => {
        const run = await setup(['--scope', 'query:read'], {
            stdoutIsTTY: true,
            answers: ['environment', 'production'],
            respond: policyApi(),
        })

        expect(run.exitCode).toBe(0)
        expect(
            (run.requests.find((request) => request.url === REQUESTS)?.body as { conditions?: unknown } | undefined)
                ?.conditions
        ).toEqual({ environment: 'production' })
    })

    test('a preset value goes into the condition exactly as typed', async () => {
        const run = await setup(['--preset', "branch_push=v$&1$'", '--scope', 'query:read'], { respond: policyApi() })

        expect(
            (run.requests.find((request) => request.url === REQUESTS)?.body as { conditions?: unknown } | undefined)
                ?.conditions
        ).toEqual({ event_name: 'push', ref: "refs/heads/v$&1$'" })
    })

    test.each([
        [
            'asks an agent for the organization every policy needs',
            ['--preset', 'branch_push=main'],
            {
                status: 'input_required',
                values: [expect.objectContaining({ option: '--preset organization=<value>' })],
            },
            undefined,
        ],
        [
            'pins the organization next to the run preset and looks the subject up with the conditions',
            ['--preset', 'branch_push=main', '--preset', 'organization=org123'],
            { status: 'pending' },
            { org_id: 'org123', forge: 'github', event_name: 'push', ref: 'refs/heads/main' },
        ],
    ])('a provider with required claims %s', async (_name, args, result, conditions) => {
        const run = await setup([...args, '--scope', 'query:read'], {
            respond: policyApi({ providers: ORG_PROVIDERS }),
        })

        expect(run.json()).toMatchObject(result)
        expect(
            (run.requests.find((request) => request.url === REQUESTS)?.body as { conditions?: unknown } | undefined)
                ?.conditions
        ).toEqual(conditions)
        if (conditions) {
            expect(run.requests.find((request) => request.url.includes('resolve_subject'))?.url).toContain(
                'condition=forge%3Dgithub'
            )
        }
    })

    test('a token in the origin remote never reaches PostHog', async () => {
        const run = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], {
            files: {
                ...REPOSITORY,
                '/work/.git/config':
                    '[remote "origin"]\n\turl = https://bot:secret@ci.example.com/acme/web.git?token=secret\n',
            },
            respond: policyApi(),
        })

        expect(run.exitCode).toBe(0)
        expect(JSON.stringify(run.requests)).not.toContain('secret')
        expect(run.requests.find((request) => request.url.includes('resolve_subject'))?.url).toContain(
            'subject_name=acme%2Fweb'
        )
    })

    test('a repository PostHog can not look up points to --subject-id', async () => {
        const run = await setup(['--preset', 'branch_push=main', '--scope', 'query:read'], {
            respond: (url) =>
                url.startsWith(`${REQUESTS}resolve_subject/`)
                    ? { status: 404, body: { detail: 'No repository acme/web that PostHog can see.' } }
                    : policyApi()(url),
        })

        expect(run.error()).toMatchObject({
            message: 'PostHog answered with HTTP 404: No repository acme/web that PostHog can see.',
        })
        expect(run.error().hint).toContain('--subject-id')
    })
})
