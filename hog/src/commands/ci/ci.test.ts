import { afterAll, describe, expect, mock, test } from 'bun:test'
import { z } from 'zod'

import * as providers from '@/ci/providers'
import { FAKE_WORKLOAD_PROVIDER, readJson, runHog, TEST_CREDENTIALS, type FakeRuntimeOptions } from '@/testing'

mock.module('@/ci/providers', () => ({ ...providers, WORKLOAD_PROVIDERS: [FAKE_WORKLOAD_PROVIDER] }))
afterAll(() => {
    mock.module('@/ci/providers', () => providers)
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

// The request API: a lookup, a new request, then `pendingPolls` answers of "still pending" before `final`.
function policyApi(options: { canApprove?: boolean; pendingPolls?: number; final?: string } = {}) {
    let polls = 0
    const created = { ...CREATED, can_approve: options.canApprove ?? false }
    return (url: string): { status: number; body: unknown } => {
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
        const run = await setup(['--branch', 'main', '--scope', 'query:read', '--scope', 'error_tracking:write'], {
            respond: policyApi(),
        })

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
            approver: 'an organization admin (Olive Owner)',
            next: 'hog ci setup --wait',
            snippet: expect.stringContaining(`HOG_PROJECT_ID: 7`),
        })
        expect(readJson(run.files[PENDING_FILE] ?? '{}')).toMatchObject({ requestId: 'req-1', provider: 'fake_ci' })
    })

    test.each([
        ['an admin waits at the terminal until they approve it', true, 'Approved.', 2],
        [
            'a member gets the link to send an admin and does not wait',
            false,
            'Only an organization admin (Olive Owner) can approve it',
            0,
        ],
    ])('%s', async (_name, canApprove, shown, polls) => {
        const run = await setup(['--environment', 'production', '--scope', 'query:read'], {
            stdoutIsTTY: true,
            respond: policyApi({ canApprove, pendingPolls: 1 }),
        })

        expect(run.exitCode).toBe(0)
        expect(run.stdout).toContain(shown)
        expect(run.stdout).toContain('HOG_HOST: https://ph.example.com')
        expect(run.requests.filter((request) => request.url === `${REQUESTS}req-1/`)).toHaveLength(polls)
        expect(PENDING_FILE in run.files).toBe(!canApprove)
    })

    test('--wait resumes the request an earlier run started and prints the snippet once approved', async () => {
        const first = await setup(['--branch', 'main', '--scope', 'query:read'], { respond: policyApi() })
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
        ['reuses the request while it waits for an admin', 'pending', 1],
        ['starts a new request once an admin resolved the last one', 'rejected', 2],
    ])('running it again %s', async (_name, lastStatus, created) => {
        const args = ['--branch', 'main', '--scope', 'query:read']
        const first = await setup(args, { respond: policyApi() })
        const api = policyApi({ final: lastStatus })
        const run = await setup(args, { files: first.files, respond: api })

        expect(run.exitCode).toBe(0)
        expect(run.requests.filter((request) => request.url === REQUESTS && request.method === 'POST')).toHaveLength(
            created - 1
        )
    })

    test('--wait gives up after a while and keeps the request for the next --wait', async () => {
        const first = await setup(['--branch', 'main', '--scope', 'query:read'], { respond: policyApi() })
        const run = await runHog(['ci', 'setup', '--wait'], {
            env: TEST_CREDENTIALS,
            files: first.files,
            respond: policyApi({ pendingPolls: 1_000 }),
        })

        expect(run.error().code).toBe('policy_request_still_pending')
        expect(PENDING_FILE in run.files).toBe(true)
    })

    test.each([
        ['no scope', ['--branch', 'main'], REPOSITORY, 'missing_scopes'],
        ['no branch or environment', ['--scope', 'query:read'], REPOSITORY, 'missing_conditions'],
        [
            'no CI config in the repository',
            ['--branch', 'main', '--scope', 'query:read'],
            { '/work/.git/config': REPOSITORY['/work/.git/config'] },
            'provider_not_detected',
        ],
    ])('stops before asking PostHog when it has %s', async (_name, args, files, code) => {
        const run = await setup(args, { files, respond: policyApi() })

        expect(run.exitCode).not.toBe(0)
        expect(run.error().code).toBe(code)
        expect(run.requests.some((request) => request.url === REQUESTS)).toBe(false)
    })

    test('a repository PostHog can not look up points to --subject-id', async () => {
        const run = await setup(['--branch', 'main', '--scope', 'query:read'], {
            respond: (url) =>
                url.startsWith(`${REQUESTS}resolve_subject/`)
                    ? { status: 404, body: { detail: 'No repository acme/web that PostHog can see.' } }
                    : policyApi()(url),
        })

        expect(run.error()).toMatchObject({ message: 'No repository acme/web that PostHog can see.' })
        expect(run.error().hint).toContain('--subject-id')
    })
})
