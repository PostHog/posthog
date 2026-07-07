/**
 * Real Docker sandbox e2e — provisions an actual container from the
 * canonical `posthog/agent-sandbox-host` image, lays out a trivial custom
 * tool, dispatches an invoke, asserts the response, releases.
 *
 * **Opt-in by docker availability**: skipped unless `docker info` works and
 * the image is present locally. Build the image first:
 *
 *   cd services/agent-sandbox-host && docker build -t posthog/agent-sandbox-host:dev .
 *
 * Mirrors `sandbox-modal.test.ts` so we get coverage of both backends
 * against the same dispatcher wire format.
 */

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { describe, expect, it } from 'vitest'

import { DockerSandboxPool } from './sandbox-docker'

const exec = promisify(execFile)

const IMAGE = process.env.SANDBOX_DOCKER_IMAGE ?? 'posthog/agent-sandbox-host:dev'

async function dockerImageAvailable(): Promise<boolean> {
    try {
        await exec('docker', ['info'], { timeout: 5_000 })
    } catch {
        return false
    }
    try {
        // `docker image inspect` returns non-zero if the image isn't present
        // locally. We don't auto-pull because the canonical image lives in
        // GHCR behind auth; CI / dev users build it locally.
        await exec('docker', ['image', 'inspect', IMAGE], { timeout: 5_000 })
        return true
    } catch {
        return false
    }
}

const HAS_DOCKER = await dockerImageAvailable()

const ECHO_TOOL_JS = `
module.exports = {
    id: 'echo',
    actions: {
        default: (args, ctx) => ({
            sum: args.a + args.b,
            secret_ref: ctx.secrets.ref('TEST_SECRET'),
            echoed: args.note,
        }),
    },
}
`

const maybeDescribe = HAS_DOCKER ? describe : describe.skip

maybeDescribe('DockerSandboxPool: real e2e', () => {
    it('acquires a container, lays out a tool, dispatches an invoke, terminates', async () => {
        const pool = new DockerSandboxPool({ image: IMAGE })
        const sessionId = `docker-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

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
            nonces: { TEST_SECRET: 'nonce_docker_abc' },
        })

        try {
            const ok = await sandbox.invoke({
                toolId: 'echo',
                action: 'default',
                args: { a: 4, b: 5, note: 'hello docker' },
                timeoutMs: 10_000,
            })
            expect(ok).toEqual({
                ok: true,
                result: {
                    sum: 9,
                    secret_ref: 'nonce_docker_abc',
                    echoed: 'hello docker',
                },
            })

            // Unknown tool → typed error from the runner-side check.
            const missing = await sandbox.invoke({
                toolId: 'does-not-exist',
                action: 'default',
                args: {},
            })
            // DockerSandbox doesn't pre-check toolIds the way ModalSandbox
            // does — the dispatcher inside the container handles it. So
            // the error code comes from the dispatcher rather than the
            // pool. Either is acceptable; assert on the failure shape.
            expect(missing.ok).toBe(false)
            if (!missing.ok) {
                expect(['tool_not_loaded', 'tool_not_found']).toContain(missing.error.code)
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
            // providerSandboxId is the docker container hash. Long
            // hex string, no colons or slashes — same shape as
            // `docker inspect -f '{{.Id}}'`.
            expect(sandbox.providerSandboxId).toMatch(/^[a-f0-9]{12,}$/)
        } finally {
            await pool.release(sessionId)
        }
    }, 60_000)
})

if (!HAS_DOCKER) {
    // eslint-disable-next-line no-console
    console.warn(
        `[sandbox-docker] e2e skipped: docker not running, or image ${IMAGE} not present locally. ` +
            `Build with: (cd services/agent-sandbox-host && docker build -t ${IMAGE} .)`
    )
}
