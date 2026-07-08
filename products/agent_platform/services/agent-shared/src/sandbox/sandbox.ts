/**
 * Sandbox contract — the one abstraction we keep.
 *
 * Per-session, not per-call: the runner acquires one sandbox per AgentSession,
 * preloaded with every custom tool the revision references. Invokes share the
 * sandbox for the session's lifetime.
 *
 * Three impls plug in behind this interface:
 *   - InProcess (tests, local dev quick-start) — no isolation, direct call.
 *   - Docker (local dev with isolation) — container per session.
 *   - Modal (prod) — managed long-lived sandboxes.
 */

export type SandboxKind = 'in-process' | 'docker' | 'modal'

export interface SandboxPool {
    readonly kind: SandboxKind
    acquireForSession(opts: AcquireOpts): Promise<Sandbox>
    release(sessionId: string): Promise<void>
}

export interface AcquireOpts {
    sessionId: string
    teamId: number
    tools: SandboxToolLoad[]
    /** Per-invocation `{ secretName -> nonce }` map — substituted at the sandbox boundary. */
    nonces: Record<string, string>
    sessionTimeoutMs?: number
    limits?: SandboxLimits
}

export interface SandboxToolLoad {
    id: string
    /** Compiled JS source — written by `agent_mgmt.write_file` on the .ts source. */
    compiledJs: string
    /** JSON schema describing this tool's accepted inputs/secrets, from defineTool. */
    schemaJson: unknown
}

export interface SandboxLimits {
    wallMs: number
    memoryMb: number
    /**
     * Optional CPU reservation in (fractional) cores. Honored by Modal as a
     * soft reservation; Docker uses `--cpus`. InProcess ignores. When unset
     * each backend falls back to its own default (Modal ≈ 0.25 cores).
     */
    cpuCores?: number
}

export interface InvokeRequest {
    toolId: string
    action: string
    args: unknown
    timeoutMs?: number
}

export type InvokeResponse = { ok: true; result: unknown } | { ok: false; error: { code: string; message: string } }

export interface Sandbox {
    readonly sessionId: string
    /**
     * Provider-side identifier suitable for out-of-process termination —
     * Modal's `ap-...` sandbox id, Docker's container hash, etc. Persisted to
     * `agent_sandbox_instance.provider_sandbox_id` so the janitor can reap
     * orphans when the owning runner pod dies. InProcess sandboxes use the
     * sessionId (there is no separate provider handle).
     */
    readonly providerSandboxId: string
    invoke(req: InvokeRequest): Promise<InvokeResponse>
    /** True if the sandbox is still alive. */
    isAlive(): Promise<boolean>
}

export const DEFAULT_LIMITS: SandboxLimits = {
    wallMs: 30_000,
    memoryMb: 512,
}
