/**
 * Out-of-process termination helper for sandboxes the runner that created
 * them can no longer reach (pod was killed, lost its lease, etc.). The
 * janitor's sandbox sweep calls into this layer for each stale
 * `agent_sandbox_instance` row.
 *
 * One backend per `SandboxKind`:
 *   - `modal`        — Modal SDK: `client.sandboxes.fromId(id).terminate()`.
 *   - `in-process`   — no-op; the sandbox died with the runner process.
 *   - `docker`       — not reachable from the janitor pod (no shared docker
 *                      socket); treated as already-gone.
 *
 * `terminate()` is **idempotent** — calling it on a sandbox that's already
 * dead returns `{ ok: true, reason: 'already gone' }`. The sweep relies on
 * this to mark a row terminated even if Modal's own timeout reaped the
 * sandbox first.
 */

import type { SandboxKind } from './sandbox'

export interface TerminationResult {
    ok: boolean
    /** Free-form. Optional for ok=true; carries the failure reason when ok=false. */
    reason?: string
}

export interface SandboxTerminator {
    terminate(kind: SandboxKind, providerSandboxId: string): Promise<TerminationResult>
}

/**
 * Routes by `SandboxKind`. The Modal client is lazy-imported the first time
 * a `modal` termination is requested — janitors that never see a Modal row
 * pay zero gRPC startup cost.
 */
export class MultiBackendSandboxTerminator implements SandboxTerminator {
    private modalTerminator: ModalLikeTerminator | null = null

    constructor(private readonly modalClientFactory: ModalClientFactory | null = null) {}

    async terminate(kind: SandboxKind, providerSandboxId: string): Promise<TerminationResult> {
        if (kind === 'in-process') {
            // The sandbox shared the runner pod's memory. When that pod
            // died the sandbox died with it; nothing to clean up.
            return { ok: true, reason: 'in-process: died with runner' }
        }
        if (kind === 'docker') {
            // Docker sandboxes run on the runner host's docker daemon — the
            // janitor pod can't reach that socket in prod. Treat as gone;
            // the per-host docker reaper handles real cleanup if there is
            // one. Local dev with both processes on the same host can wire
            // its own terminator.
            return { ok: true, reason: 'docker: not reachable from janitor' }
        }
        if (kind === 'modal') {
            if (!this.modalClientFactory) {
                return { ok: false, reason: 'modal terminator not configured' }
            }
            if (!this.modalTerminator) {
                this.modalTerminator = await this.modalClientFactory()
            }
            return this.modalTerminator.terminate(providerSandboxId)
        }
        // Exhaustiveness: every SandboxKind handled above. A new kind
        // without a branch here is a type error.
        const _exhaustive: never = kind
        return { ok: false, reason: `unknown provider kind: ${_exhaustive as string}` }
    }
}

/* -------------------------------------------------------------------------- */
/* Modal impl                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * Narrow shape over `client.sandboxes.fromId().terminate()` — keeps this
 * file free of the heavy `modal` import so consumers that never reap Modal
 * (tests, dev) don't pay for the SDK.
 */
export interface ModalLikeTerminator {
    terminate(providerSandboxId: string): Promise<TerminationResult>
}

export type ModalClientFactory = () => Promise<ModalLikeTerminator>

/**
 * Default factory: imports `modal` lazily and constructs a `ModalClient` from
 * MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in env. Termination is idempotent —
 * looking up a sandbox that's already gone resolves to `{ ok: true,
 * reason: 'already gone' }`.
 */
export function createModalSandboxTerminator(): ModalClientFactory {
    return async () => {
        const { ModalClient } = await import('modal')
        const client = new ModalClient()
        return {
            async terminate(providerSandboxId: string): Promise<TerminationResult> {
                try {
                    const sb = await client.sandboxes.fromId(providerSandboxId)
                    await sb.terminate()
                    return { ok: true }
                } catch (err) {
                    const message = (err as Error).message ?? String(err)
                    // Modal's gRPC layer surfaces a `NotFound` for already-gone
                    // sandboxes. Treat as success so the sweep can flip the row
                    // to terminated and stop retrying.
                    if (/not.?found/i.test(message)) {
                        return { ok: true, reason: 'already gone' }
                    }
                    return { ok: false, reason: message }
                }
            },
        }
    }
}
