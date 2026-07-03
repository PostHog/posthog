/**
 * Pure-unit tests for ModalSandboxPool that don't need real Modal creds.
 * Real-Modal e2e tests live in sandbox-modal.test.ts and are opt-in by env.
 *
 * The case we want to lock down here is the regression Greptile caught:
 * if the lazy client/app/image init rejects on the FIRST acquire, the
 * rejected Promise must NOT be cached in `clientPromise` — otherwise every
 * subsequent acquire skips re-init and rethrows the same stale error
 * forever, wedging the pool until pod restart.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AcquireOpts } from './sandbox'
import { ModalSandboxPool, resolveEgressOpts, resolveRegion } from './sandbox-modal'

const ACQUIRE_INPUT: AcquireOpts = {
    sessionId: 'unit-test-session',
    teamId: 1,
    tools: [],
    nonces: {},
}

describe('ModalSandboxPool: client-init failure recovery', () => {
    beforeEach(() => {
        vi.resetModules()
        vi.clearAllMocks()
    })

    it('does NOT cache a rejected client promise — second acquire re-attempts the handshake', async () => {
        // Track every constructor call so we can prove re-init happens.
        // Regular `function` (not arrow) so the spy is constructable — the SUT
        // does `new ModalClient()`, and vitest 4's tinyspy uses Reflect.construct
        // on the impl, which throws on a non-constructable arrow.
        const clientCtor = vi.fn(function () {
            throw new Error('transient modal auth blip')
        })

        // vi.doMock is hoisted across `import` boundaries; resetModules() in
        // beforeEach makes sure the next dynamic import picks this up fresh.
        vi.doMock('modal', () => ({
            ModalClient: clientCtor,
        }))

        const pool = new ModalSandboxPool({ appName: 'unit-test-app' })

        // First acquire: surfaces the underlying transient error.
        await expect(pool.acquireForSession(ACQUIRE_INPUT)).rejects.toThrow('transient modal auth blip')
        expect(clientCtor).toHaveBeenCalledTimes(1)

        // Second acquire (regression check): without the catch-and-clear,
        // this would skip re-init entirely and rethrow the cached error
        // without ever calling ModalClient again. With the fix, the
        // constructor must be invoked a second time.
        await expect(pool.acquireForSession(ACQUIRE_INPUT)).rejects.toThrow('transient modal auth blip')
        expect(clientCtor).toHaveBeenCalledTimes(2)
    })

    it('region resolves from MODAL_REGION env, falls back to CLOUD_DEPLOYMENT, then us-east', () => {
        const cases: Array<{ env: NodeJS.ProcessEnv; expected: string; label: string }> = [
            { env: { MODAL_REGION: 'asia-east' }, expected: 'asia-east', label: 'MODAL_REGION env wins' },
            { env: { CLOUD_DEPLOYMENT: 'US' }, expected: 'us-east', label: 'US deployment → us-east' },
            { env: { CLOUD_DEPLOYMENT: 'EU' }, expected: 'eu-west', label: 'EU deployment → eu-west' },
            {
                env: { CLOUD_DEPLOYMENT: 'unknown' },
                expected: 'us-east',
                label: 'unknown deployment falls back to us-east',
            },
            { env: {}, expected: 'us-east', label: 'nothing set → us-east' },
            {
                env: { MODAL_REGION: 'asia-east', CLOUD_DEPLOYMENT: 'EU' },
                expected: 'asia-east',
                label: 'MODAL_REGION beats CLOUD_DEPLOYMENT',
            },
        ]
        for (const { env, expected, label } of cases) {
            expect(resolveRegion(env), label).toBe(expected)
        }
    })

    it('ModalSandbox.invoke omits timeoutMs from exec opts when caller does not set it', async () => {
        // The Modal SDK rejects `exec({ timeoutMs: 0 })` with
        // "timeoutMs must be positive" even though its own type def says
        // "default 0 (no timeout)". This was a real bug caught only by the
        // real-Modal e2e in the previous round. Lock it down at the unit
        // layer so a refactor that reverts the conditional to
        // `timeoutMs: req.timeoutMs ?? 0` fails fast.
        const execCallArgs: Array<{ cmd: string[]; opts: Record<string, unknown> }> = []
        const fakeProc = {
            wait: vi.fn().mockResolvedValue(0),
            stderr: { readText: vi.fn().mockResolvedValue('') },
        }
        const handle = {
            sandboxId: 'sb-timeout-test',
            filesystem: {
                makeDirectory: vi.fn().mockResolvedValue(undefined),
                writeText: vi.fn().mockResolvedValue(undefined),
                readText: vi.fn().mockResolvedValue('{"ok":true,"result":42}'),
            },
            exec: vi.fn().mockImplementation((cmd: string[], opts: Record<string, unknown>) => {
                execCallArgs.push({ cmd, opts })
                return Promise.resolve(fakeProc)
            }),
            poll: vi.fn().mockResolvedValue(null),
            terminate: vi.fn().mockResolvedValue(undefined),
        }
        const clientCtor = vi.fn(function () {
            return {
                apps: { fromName: vi.fn().mockResolvedValue({}) },
                images: { fromRegistry: vi.fn().mockReturnValue({}) },
                sandboxes: { create: vi.fn().mockResolvedValue(handle) },
            }
        })
        vi.doMock('modal', () => ({ ModalClient: clientCtor }))

        const pool = new ModalSandboxPool({ appName: 'unit-test-app' })
        const sandbox = await pool.acquireForSession({
            sessionId: 's',
            teamId: 1,
            tools: [{ id: 'noop', compiledJs: 'module.exports={id:"noop",actions:{default:()=>1}}', schemaJson: {} }],
            nonces: {},
        })

        // No timeoutMs supplied → must NOT be in execOpts.
        await sandbox.invoke({ toolId: 'noop', action: 'default', args: {} })
        expect(execCallArgs).toHaveLength(1)
        expect(execCallArgs[0].opts).not.toHaveProperty('timeoutMs')
        expect(execCallArgs[0].opts).toMatchObject({ stdout: 'pipe', stderr: 'pipe' })

        // timeoutMs: 0 also must NOT propagate (same regression — Modal
        // rejects 0 even though it's "default"). Treated as absence.
        await sandbox.invoke({ toolId: 'noop', action: 'default', args: {}, timeoutMs: 0 })
        expect(execCallArgs).toHaveLength(2)
        expect(execCallArgs[1].opts).not.toHaveProperty('timeoutMs')

        // Positive timeoutMs IS passed through.
        await sandbox.invoke({ toolId: 'noop', action: 'default', args: {}, timeoutMs: 30_000 })
        expect(execCallArgs).toHaveLength(3)
        expect(execCallArgs[2].opts).toMatchObject({ timeoutMs: 30_000 })
    })

    it('proceeds normally once the handshake succeeds on a retry', async () => {
        let callCount = 0

        const acquiredHandle = {
            sandboxId: 'sb-unit-test-handle',
            filesystem: {
                makeDirectory: vi.fn().mockResolvedValue(undefined),
                writeText: vi.fn().mockResolvedValue(undefined),
            },
            poll: vi.fn().mockResolvedValue(null),
            terminate: vi.fn().mockResolvedValue(undefined),
        }

        const clientCtor = vi.fn(function () {
            callCount++
            if (callCount === 1) {
                throw new Error('transient blip')
            }
            return {
                apps: {
                    fromName: vi.fn().mockResolvedValue({ _appId: 'unit-app' }),
                },
                images: {
                    fromRegistry: vi.fn().mockReturnValue({ _imageRef: 'unit-image' }),
                },
                sandboxes: {
                    create: vi.fn().mockResolvedValue(acquiredHandle),
                },
            }
        })

        vi.doMock('modal', () => ({
            ModalClient: clientCtor,
        }))

        const pool = new ModalSandboxPool({ appName: 'unit-test-app' })

        await expect(pool.acquireForSession(ACQUIRE_INPUT)).rejects.toThrow('transient blip')
        const sandbox = await pool.acquireForSession(ACQUIRE_INPUT)
        expect(sandbox.providerSandboxId).toBe('sb-unit-test-handle')
        expect(clientCtor).toHaveBeenCalledTimes(2)
    })
})

describe('ModalSandboxPool: egress policy', () => {
    it.each<[string, string[] | undefined, Record<string, unknown>]>([
        ['undefined → block', undefined, { blockNetwork: true }],
        ['empty array → block', [], { blockNetwork: true }],
        [
            'non-empty CIDR list → allowlist (must not also set blockNetwork)',
            ['10.0.0.0/8', '192.168.0.0/16'],
            { outboundCidrAllowlist: ['10.0.0.0/8', '192.168.0.0/16'] },
        ],
    ])('resolveEgressOpts(%s)', (_label, input, expected) => {
        // Modal rejects `blockNetwork` and `outboundCidrAllowlist` together,
        // so the allowlist arm intentionally omits `blockNetwork`.
        expect(resolveEgressOpts(input)).toEqual(expected)
    })

    async function captureCreateOpts(poolOpts: { outboundCidrAllowlist?: string[] }): Promise<Record<string, unknown>> {
        const createMock = vi.fn().mockResolvedValue({
            sandboxId: 'sb-egress-test',
            filesystem: {
                makeDirectory: vi.fn().mockResolvedValue(undefined),
                writeText: vi.fn().mockResolvedValue(undefined),
            },
            poll: vi.fn().mockResolvedValue(null),
            terminate: vi.fn().mockResolvedValue(undefined),
        })
        vi.doMock('modal', () => ({
            ModalClient: vi.fn(function () {
                return {
                    apps: { fromName: vi.fn().mockResolvedValue({}) },
                    images: { fromRegistry: vi.fn().mockReturnValue({}) },
                    sandboxes: { create: createMock },
                }
            }),
        }))
        const pool = new ModalSandboxPool({ appName: 'unit-test-app', ...poolOpts })
        await pool.acquireForSession(ACQUIRE_INPUT)
        // create(app, image, opts) — opts is the third arg.
        return createMock.mock.calls[0][2] as Record<string, unknown>
    }

    it('sandboxes.create blocks the network by default (no allowlist)', async () => {
        const opts = await captureCreateOpts({})
        expect(opts.blockNetwork).toBe(true)
        expect(opts).not.toHaveProperty('outboundCidrAllowlist')
    })

    it('sandboxes.create uses the configured CIDR allowlist instead of blocking', async () => {
        const opts = await captureCreateOpts({ outboundCidrAllowlist: ['10.1.0.0/16'] })
        expect(opts.outboundCidrAllowlist).toEqual(['10.1.0.0/16'])
        expect(opts).not.toHaveProperty('blockNetwork')
    })
})
