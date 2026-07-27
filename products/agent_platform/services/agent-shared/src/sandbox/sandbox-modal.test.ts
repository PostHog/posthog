/**
 * Real Modal sandbox e2e — provisions an actual Modal sandbox, lays out a
 * trivial custom tool, dispatches an invoke, asserts the response, releases.
 *
 * **Opt-in by env**: skipped unless both `MODAL_TOKEN_ID` and
 * `MODAL_TOKEN_SECRET` are set (in `process.env` or repo-root `.env`).
 * Mirrors the `real-inference.test.ts` pattern so CI without Modal creds
 * stays green and local dev runs the test automatically when the dev env
 * has tokens.
 *
 * Cost: each run provisions one Modal sandbox for ~30s of wall time. Modal's
 * free tier covers this; the test self-cleans via `release()` (`sb.terminate()`
 * under the hood). Override the cleanup behaviour by setting
 * `MODAL_E2E_KEEP_SANDBOX=1` to leave it running for inspection — you must
 * `modal sandbox terminate <id>` manually if so.
 */

import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { ModalSandboxPool } from './sandbox-modal'
import { createModalSandboxTerminator, MultiBackendSandboxTerminator } from './sandbox-terminator'

// Walk up from this file looking for a repo-root `.env` and load it into
// process.env. Mirrors real-inference.test.ts so local dev with tokens in
// .env "just works"; CI without `.env` falls through to the SKIP path.
function loadRepoEnv(): void {
    let dir = dirname(fileURLToPath(import.meta.url))
    for (let i = 0; i < 8; i++) {
        const candidate = resolve(dir, '.env')
        if (existsSync(candidate)) {
            try {
                process.loadEnvFile(candidate)
            } catch {
                /* loadEnvFile throws on parse errors; degrade rather than crash. */
            }
            break
        }
        const parent = dirname(dir)
        if (parent === dir) {
            break
        }
        dir = parent
    }
    // Node's built-in fetch + gRPC do NOT read macOS' keychain trust store —
    // without an explicit CA bundle the Modal gRPC handshake fails with
    // `unable to get local issuer certificate`. Point Node at the openssl
    // bundle that ships on darwin if the caller hasn't already pinned one.
    if (!process.env.SSL_CERT_FILE && !process.env.NODE_EXTRA_CA_CERTS) {
        const darwinDefault = '/etc/ssl/cert.pem'
        if (existsSync(darwinDefault)) {
            process.env.SSL_CERT_FILE = darwinDefault
            process.env.NODE_EXTRA_CA_CERTS = darwinDefault
        }
    }
}
loadRepoEnv()

const HAS_CREDS = Boolean(process.env.MODAL_TOKEN_ID && process.env.MODAL_TOKEN_SECRET)
// Skip even with Modal creds unless an image override is provided. The
// default `:master` tag only exists once the image lands on main; for an
// in-flight branch you'd typically run the test as
//   SANDBOX_HOST_IMAGE=ghcr.io/posthog/posthog-agent-sandbox-host:pr-NN \
//     pnpm --filter @posthog/agent-shared test src/sandbox/sandbox-modal
// — gating here keeps `pnpm test` green on branches where `:master`
// might lag the source.
const HAS_IMAGE = Boolean(process.env.SANDBOX_HOST_IMAGE)
const KEEP = process.env.MODAL_E2E_KEEP_SANDBOX === '1'

// CommonJS source for the test tool. Defines a single `default` action that
// adds two numbers and echoes the nonce for a `TEST_SECRET`. Kept simple so
// the assertions stay tight — anything we add here is hard to debug remotely.
const ECHO_TOOL_JS = `
module.exports = {
    id: 'echo',
    actions: {
        default: (args, ctx) => {
            const secret = ctx.secrets.ref('TEST_SECRET')
            return {
                sum: args.a + args.b,
                secret_ref: secret,
                echoed: args.note,
            }
        },
    },
}
`

const maybeDescribe = HAS_CREDS && HAS_IMAGE ? describe : describe.skip

maybeDescribe('ModalSandboxPool: real e2e', () => {
    it('acquires a sandbox, lays out a tool, dispatches an invoke, terminates', async () => {
        const pool = new ModalSandboxPool({
            // Per-test app so concurrent runs don't collide. Modal will
            // create-if-missing.
            appName: process.env.MODAL_APP_NAME ?? 'posthog-agent-sandbox-test',
            // Override the published image when validating an in-flight PR
            // before the `:master` tag exists. The chart sets this from
            // state.yaml in prod.
            image: process.env.SANDBOX_HOST_IMAGE,
            // Tight upper bound — if the test wedges, the sandbox dies on
            // its own within 2 minutes.
            defaultSessionTimeoutMs: 120_000,
        })

        const sessionId = `test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const sandbox = await pool.acquireForSession({
            sessionId,
            teamId: 1,
            tools: [
                {
                    id: 'echo',
                    compiledJs: ECHO_TOOL_JS,
                    schemaJson: { type: 'object' },
                },
            ],
            nonces: { TEST_SECRET: 'nonce_abc123' },
        })

        try {
            const ok = await sandbox.invoke({
                toolId: 'echo',
                action: 'default',
                args: { a: 2, b: 3, note: 'hello modal' },
                timeoutMs: 30_000,
            })
            expect(ok).toEqual({
                ok: true,
                result: {
                    sum: 5,
                    secret_ref: 'nonce_abc123',
                    echoed: 'hello modal',
                },
            })

            // Unknown tool → typed error, no crash.
            const missing = await sandbox.invoke({
                toolId: 'does-not-exist',
                action: 'default',
                args: {},
            })
            expect(missing.ok).toBe(false)
            if (!missing.ok) {
                expect(missing.error.code).toBe('tool_not_loaded')
            }

            // Bad action on a real tool → dispatcher reports it.
            const badAction = await sandbox.invoke({
                toolId: 'echo',
                action: 'nope',
                args: {},
            })
            expect(badAction.ok).toBe(false)
            if (!badAction.ok) {
                expect(badAction.error.code, `error: ${JSON.stringify(badAction.error)}`).toBe('action_not_found')
            }

            expect(await sandbox.isAlive()).toBe(true)

            // providerSandboxId must be the real Modal `ap-...` id so the
            // janitor can look it up out-of-process. Any other shape (e.g.
            // the runner's session UUID) defeats the whole point of the
            // tracking row.
            expect(sandbox.providerSandboxId).toMatch(/^sb-/)
        } finally {
            if (!KEEP) {
                await pool.release(sessionId)
            }
        }
    }, 120_000) // warm image, but a cold image pull can push past 30s. // 2-minute test timeout: Modal sandbox boot is typically 5-15s on a

    it('reaper terminates a Modal sandbox out-of-process by providerSandboxId', async () => {
        const pool = new ModalSandboxPool({
            appName: process.env.MODAL_APP_NAME ?? 'posthog-agent-sandbox-test',
            image: process.env.SANDBOX_HOST_IMAGE,
            defaultSessionTimeoutMs: 120_000,
        })

        const sessionId = `reap-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const sandbox = await pool.acquireForSession({
            sessionId,
            teamId: 1,
            tools: [{ id: 'echo', compiledJs: ECHO_TOOL_JS, schemaJson: { type: 'object' } }],
            nonces: { TEST_SECRET: 'nonce_xyz' },
        })

        const providerSandboxId = sandbox.providerSandboxId
        expect(providerSandboxId).toMatch(/^sb-/)

        // Spawn a *fresh* terminator (mimics the janitor — separate
        // process, separate client) and reap by id only. The original
        // pool isn't consulted; this proves the row's
        // provider_sandbox_id alone is enough to kill the compute.
        const terminator = new MultiBackendSandboxTerminator(createModalSandboxTerminator())
        const first = await terminator.terminate('modal', providerSandboxId)
        expect(first.ok, `first terminate: ${JSON.stringify(first)}`).toBe(true)

        // Idempotency: a second terminate of the same id resolves ok
        // (either Modal returns success again or the not-found branch
        // catches it and treats it as already gone).
        const second = await terminator.terminate('modal', providerSandboxId)
        expect(second.ok, `second terminate: ${JSON.stringify(second)}`).toBe(true)

        // The sandbox should report dead after terminate. Modal's poll()
        // is eventually consistent — it takes 1-2s for the state update
        // to propagate. Poll for a few seconds to avoid flakes.
        const deadline = Date.now() + 10_000
        let alive = true
        while (Date.now() < deadline) {
            alive = await sandbox.isAlive()
            if (!alive) {
                break
            }
            await new Promise((r) => setTimeout(r, 200))
        }
        expect(alive).toBe(false)
    }, 120_000)
})

if (!HAS_CREDS) {
    // Match real-inference.test.ts: surface a clear skip reason instead of
    // a silent green-when-empty result.
    // eslint-disable-next-line no-console
    console.warn(
        '[sandbox-modal] e2e skipped: MODAL_TOKEN_ID + MODAL_TOKEN_SECRET not set. Add them to repo-root .env to enable.'
    )
}
