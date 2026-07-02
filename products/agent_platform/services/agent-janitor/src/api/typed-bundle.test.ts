/**
 * Unit tests for the dry-run admission control in the typed-bundle router.
 *
 * The wire-level dry-run behaviour (real sandbox, real stores) is covered by
 * `agent-tests/src/cases/typed-bundle-authoring.test.ts`; this file pins the
 * in-flight cap, which needs *concurrent* requests held open mid-acquire —
 * deterministic here via deferred promises on a stub pool, flaky there via
 * sleeps in real sandboxes.
 */

import express from 'express'
import request from 'supertest'

import type { BundleStore, RevisionStore, SandboxPool } from '@posthog/agent-shared'

import { buildTypedBundleRouter } from './typed-bundle'

const REV_ID = '00000000-0000-4000-8000-00000000ab01'

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
    let resolve!: (v: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

/** Stores stubbed to the minimal draft-revision surface the dry-run path reads. */
function stubStores(): { revisions: RevisionStore; bundles: BundleStore } {
    const revisions = {
        async getRevisionRaw() {
            return { id: REV_ID, application_id: 'app-1', state: 'draft', spec: {} }
        },
        async getApplication() {
            return { id: 'app-1', team_id: 1 }
        },
    } as unknown as RevisionStore
    const bundles = {
        async isFrozen() {
            return false
        },
        async readText(_rev: string, path: string) {
            return path.endsWith('compiled.js') ? 'module.exports = {}' : '{}'
        },
    } as unknown as BundleStore
    return { revisions, bundles }
}

describe('dry-run sandbox guards', () => {
    it('429s past the cap and frees the slot when the held run finishes', async () => {
        // Pool whose acquire blocks until the test releases it, so requests
        // can be held in flight deterministically.
        const acquireEntered = deferred<void>()
        const acquireGate = deferred<void>()
        const sandboxes = {
            async acquireForSession() {
                acquireEntered.resolve()
                await acquireGate.promise
                return {
                    async invoke() {
                        return { ok: true, result: { ran: true } }
                    },
                }
            },
            async release() {},
        } as unknown as SandboxPool

        const app = express()
        app.use(express.json())
        app.use('/revisions/:id', buildTypedBundleRouter({ ...stubStores(), sandboxes, dryRunMaxConcurrent: 1 }))
        const dryRun = (): request.Test =>
            request(app).post(`/revisions/${REV_ID}/tools/echo/dry_run`).send({ args: {} })

        // A acquires the only slot and parks inside acquireForSession.
        const a = dryRun()
        const aDone = a.then((r) => r)
        await acquireEntered.promise

        // B arrives while A holds the slot → rejected, not queued.
        const b = await dryRun()
        expect(b.status).toBe(429)
        expect(b.body).toEqual({ error: 'dry_run_throttled', max_concurrent: 1 })

        // A completes normally once released.
        acquireGate.resolve()
        const aRes = await aDone
        expect(aRes.status).toBe(200)
        expect(aRes.body).toMatchObject({ ok: true, result: { ran: true } })

        // The slot was freed — a follow-up run is admitted (catches a
        // leaked counter if the finally-decrement is ever dropped).
        const c = await dryRun()
        expect(c.status).toBe(200)
    })

    // The in-sandbox dispatcher timeout is cooperative — a synchronous
    // busy-loop tool body means the backend invoke never resolves. The
    // janitor-side wall clock must return a timeout AND free the slot,
    // or two such calls wedge dry-run for the whole process.
    it('times out a hung invoke janitor-side, destroys the sandbox, and frees the slot', async () => {
        const released = deferred<void>()
        const sandboxes = {
            async acquireForSession() {
                return {
                    invoke: () => new Promise(() => {}),
                }
            },
            async release() {
                released.resolve()
            },
        } as unknown as SandboxPool

        const app = express()
        app.use(express.json())
        app.use(
            '/revisions/:id',
            // Tiny wallMs so the test only waits out the fixed grace window.
            buildTypedBundleRouter({ ...stubStores(), sandboxes, dryRunWallMs: 20, dryRunMaxConcurrent: 1 })
        )
        const dryRun = (): request.Test =>
            request(app).post(`/revisions/${REV_ID}/tools/hang/dry_run`).send({ args: {} })

        const hung = await dryRun()
        expect(hung.status).toBe(200)
        expect(hung.body).toMatchObject({ ok: false, error: { code: 'timeout' } })
        // Release ran despite the invoke never resolving — the wedged
        // sandbox is destroyed rather than orphaned.
        await released.promise

        // And the in-flight slot was freed, not pinned forever.
        const next = await dryRun()
        expect(next.status).toBe(200)
        expect(next.body).toMatchObject({ ok: false, error: { code: 'timeout' } })
    })
})
