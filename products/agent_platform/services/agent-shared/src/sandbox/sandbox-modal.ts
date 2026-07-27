/**
 * Modal sandbox pool. One Modal Sandbox per AgentSession.
 *
 * Wire format is identical to the Docker pool — both pull the same
 * `posthog-agent-sandbox-host` image which bakes `/sandbox/dispatch.js`:
 *
 *   /sandbox/dispatch.js                  — per-invoke handler (in the image).
 *   /workdir/tools/<id>/compiled.js       — author's bundled tool source.
 *   /workdir/tools/<id>/schema.json       — defineTool() input schema.
 *   /workdir/nonces.json                  — { secretName -> nonce } for ctx.secrets.ref().
 *   /workdir/req-<n>.json + res-<n>.json  — per-invoke request/response.
 *
 * Per acquire we still write the per-session bits (tools + nonces) via
 * `sandbox.filesystem.writeText` — those change per session. The dispatcher
 * itself is in the image, so we no longer pay a write cost for it.
 *
 * Modal credentials come from MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in the
 * runner pod's environment. The chart pulls those from
 * agent-platform-shared-secrets.
 *
 * Region: `MODAL_REGION` env wins; otherwise derived from `CLOUD_DEPLOYMENT`
 * (`US` → `us-east`, `EU` → `eu-west`, anything else → `us-east`). Matches
 * `products/tasks/backend/services/modal_sandbox.py` so dev cross-tenant
 * latency stays sane and EU data stays in EU.
 *
 * The Modal sandbox idles waiting for `exec()` calls — no foreground command
 * is set. `timeoutMs` upper-bounds the session lifetime so a wedged session
 * doesn't leak compute.
 *
 * Egress: the sandbox runs untrusted-ish author-supplied tool code, which by
 * design computes and returns — it does not reach out (the runner makes any
 * outbound call, through smokescreen). So we default-deny the sandbox's
 * outbound internet (`blockNetwork`), closing the open-egress exfil vector. An
 * operator can open specific CIDRs via `outboundCidrAllowlist` if a custom tool
 * ever genuinely needs direct egress. Modal's control plane (exec / filesystem)
 * is unaffected — that isn't the sandbox's own internet egress.
 */

import type { App, Image, ModalClient as ModalClientType, Sandbox as ModalSandboxHandle } from 'modal'

import { createLogger } from '../runtime/logger'
import { AcquireOpts, InvokeRequest, InvokeResponse, Sandbox, SandboxPool } from './sandbox'

const log = createLogger('sandbox-modal')

/**
 * Default base image. Canonical `posthog-agent-sandbox-host` from public
 * GHCR — bakes `/sandbox/dispatch.js` and `/sandbox/host.js`. Production
 * should pin a `@sha256:...` digest via `SANDBOX_HOST_IMAGE` because Modal
 * caches images by reference indefinitely (see Tasks's modal_sandbox.py for
 * the precedent); the `:master` default here is for dev / tests where the
 * mutable tag is fine.
 */
const DEFAULT_IMAGE_TAG = 'ghcr.io/posthog/posthog-agent-sandbox-host:master'

/** Default Modal app name. Override via `appName` ctor opt. */
const DEFAULT_APP_NAME = 'posthog-agent-sandbox'

/** Default upper bound on a Modal sandbox lifetime. Sessions cap this further. */
const DEFAULT_SESSION_TIMEOUT_MS = 60 * 60 * 1000 // 1 hour

/** Region pinning, mirrors products/tasks/backend/services/modal_sandbox.py. */
const MODAL_REGION_BY_DEPLOYMENT: Record<string, string> = {
    US: 'us-east',
    EU: 'eu-west',
}
const DEFAULT_MODAL_REGION = 'us-east'

/**
 * Exported for unit tests in `sandbox-modal-unit.test.ts`. Not part of the
 * public surface — callers should use a `ModalSandboxPool` directly.
 */
export function resolveRegion(env: NodeJS.ProcessEnv = process.env): string {
    if (env.MODAL_REGION) {
        return env.MODAL_REGION
    }
    const deployment = env.CLOUD_DEPLOYMENT
    if (deployment && MODAL_REGION_BY_DEPLOYMENT[deployment]) {
        return MODAL_REGION_BY_DEPLOYMENT[deployment]
    }
    return DEFAULT_MODAL_REGION
}

interface ModalSandboxPoolOpts {
    /** Default `posthog-agent-sandbox`. Override per environment (e.g. `posthog-agent-sandbox-dev`). */
    appName?: string
    /**
     * Container registry image. Default
     * `ghcr.io/posthog/posthog-agent-sandbox-host:master`. **In prod pin a
     * `@sha256:...` digest** — Modal caches by reference, mutable tags
     * stale-cache forever.
     */
    image?: string
    /** Hard upper bound on a session's sandbox lifetime in ms. Default 1h. */
    defaultSessionTimeoutMs?: number
    /**
     * Modal region. Default: `MODAL_REGION` env → `CLOUD_DEPLOYMENT`-derived
     * → `us-east`. Override per pool when testing cross-region.
     */
    region?: string
    /**
     * Default CPU cores when the per-acquire `limits.cpuCores` is unset.
     * Default 0.25 — most custom tools are I/O-bound.
     */
    defaultCpuCores?: number
    /**
     * Default memory cap in MiB when the per-acquire `limits.memoryMb` is
     * unset. Default 512.
     */
    defaultMemoryMiB?: number
    /**
     * CIDRs the sandbox is allowed to reach outbound. Empty / unset →
     * `blockNetwork: true` (the secure default — see the module docstring).
     * Set only to open specific egress for a custom-tool use case.
     */
    outboundCidrAllowlist?: string[]
}

/**
 * The Modal egress policy for the sandbox. Default-deny (`blockNetwork`) unless
 * an operator supplied a CIDR allowlist. `blockNetwork` and `outboundCidrAllowlist`
 * are mutually exclusive in the Modal SDK, so this returns exactly one.
 * Exported for unit tests.
 */
export function resolveEgressOpts(
    outboundCidrAllowlist?: string[]
): { blockNetwork: true } | { outboundCidrAllowlist: string[] } {
    if (outboundCidrAllowlist && outboundCidrAllowlist.length > 0) {
        return { outboundCidrAllowlist }
    }
    return { blockNetwork: true }
}

interface ModalSandboxState {
    sessionId: string
    handle: ModalSandboxHandle
    toolIds: Set<string>
    invokeCounter: number
}

class ModalSandbox implements Sandbox {
    private alive = true
    private state: ModalSandboxState
    readonly sessionId: string

    constructor(state: ModalSandboxState) {
        this.state = state
        this.sessionId = state.sessionId
    }

    /** Modal's `sb-...` sandbox id — what `client.sandboxes.fromId()` consumes. */
    get providerSandboxId(): string {
        return this.state.handle.sandboxId
    }

    async invoke(req: InvokeRequest): Promise<InvokeResponse> {
        if (!this.alive) {
            return { ok: false, error: { code: 'sandbox_released', message: 'sandbox already released' } }
        }
        if (!this.state.toolIds.has(req.toolId)) {
            return { ok: false, error: { code: 'tool_not_loaded', message: `tool ${req.toolId} not loaded` } }
        }
        const n = ++this.state.invokeCounter
        const reqPath = `/workdir/req-${n}.json`
        const resPath = `/workdir/res-${n}.json`
        try {
            await this.state.handle.filesystem.writeText(JSON.stringify(req), reqPath)
            // `timeoutMs: 0` is rejected by Modal even though the doc says
            // "default 0 (no timeout)" — only pass it when the caller
            // actually wants a bound.
            const execOpts: { stdout: 'pipe'; stderr: 'pipe'; timeoutMs?: number } = {
                stdout: 'pipe',
                stderr: 'pipe',
            }
            if (req.timeoutMs && req.timeoutMs > 0) {
                execOpts.timeoutMs = req.timeoutMs
            }
            const proc = await this.state.handle.exec(['node', '/sandbox/dispatch.js', reqPath, resPath], execOpts)
            const [exitCode, stderr] = await Promise.all([proc.wait(), proc.stderr.readText()])
            if (exitCode !== 0) {
                return {
                    ok: false,
                    error: { code: 'exec_failed', message: stderr || `exit ${exitCode}` },
                }
            }
            const body = await this.state.handle.filesystem.readText(resPath)
            return JSON.parse(body) as InvokeResponse
        } catch (err) {
            const e = err as Error
            return { ok: false, error: { code: 'modal_invoke_failed', message: e.message } }
        }
    }

    async isAlive(): Promise<boolean> {
        if (!this.alive) {
            return false
        }
        try {
            // `poll()` returns the exit code if terminated, `null` if running.
            const exitCode = await this.state.handle.poll()
            return exitCode === null
        } catch {
            return false
        }
    }

    async destroy(): Promise<void> {
        this.alive = false
        try {
            await this.state.handle.terminate()
        } catch (err) {
            log.warn({ sessionId: this.sessionId, err: (err as Error).message }, 'modal.sandbox.terminate_failed')
        }
    }
}

export class ModalSandboxPool implements SandboxPool {
    readonly kind = 'modal' as const
    private readonly bySession = new Map<string, ModalSandbox>()
    private readonly opts: ModalSandboxPoolOpts
    private clientPromise: Promise<{ client: ModalClientType; app: App; image: Image }> | null = null

    constructor(opts: ModalSandboxPoolOpts = {}) {
        this.opts = opts
    }

    private async getClient(): Promise<{ client: ModalClientType; app: App; image: Image }> {
        if (!this.clientPromise) {
            this.clientPromise = (async () => {
                // Dynamic import — keeps `modal` (gRPC + protobuf, heavy) off
                // the load path for tests / packages that never construct a
                // ModalSandboxPool. The selector imports this module
                // unconditionally; the SDK is paid for only when chosen.
                const { ModalClient } = await import('modal')
                const client = new ModalClient()
                const app = await client.apps.fromName(this.opts.appName ?? DEFAULT_APP_NAME, {
                    createIfMissing: true,
                })
                const image = client.images.fromRegistry(this.opts.image ?? DEFAULT_IMAGE_TAG)
                return { client, app, image }
            })().catch((err) => {
                // Clear so the next acquire retries the handshake. Without
                // this, a transient Modal auth blip / rate limit / network
                // failure on the FIRST acquire wedges the rejected promise
                // in the cache forever — every subsequent acquire would
                // skip the re-init guard and rethrow the same stale error
                // until the pod restarts.
                this.clientPromise = null
                throw err
            })
        }
        return this.clientPromise
    }

    async acquireForSession(opts: AcquireOpts): Promise<Sandbox> {
        const existing = this.bySession.get(opts.sessionId)
        if (existing && (await existing.isAlive())) {
            return existing
        }

        const { client, app, image } = await this.getClient()
        const timeoutMs = opts.sessionTimeoutMs ?? this.opts.defaultSessionTimeoutMs ?? DEFAULT_SESSION_TIMEOUT_MS
        const region = this.opts.region ?? resolveRegion()
        const cpu = opts.limits?.cpuCores ?? this.opts.defaultCpuCores ?? 0.25
        const memoryMiB = opts.limits?.memoryMb ?? this.opts.defaultMemoryMiB ?? 512
        // Human-readable name so the Modal dashboard is browsable. Modal
        // requires names unique within an App; suffix with sessionId so two
        // pools never collide. Truncated because Modal caps name length.
        const sandboxName = `agent-${opts.sessionId.slice(0, 24)}`

        let handle: ModalSandboxHandle
        try {
            handle = await client.sandboxes.create(app, image, {
                // No `command:` — Modal's default ("sleep indefinitely") is
                // what we want. We drive work via exec().
                timeoutMs,
                name: sandboxName,
                regions: [region],
                // CPU + memory: pass reservation and hard cap as the same
                // value (no overcommit). Modal rejects memoryLimitMiB
                // without memoryMiB and vice versa for cpuLimit/cpu, so
                // both have to be set together when either is.
                cpu,
                cpuLimit: cpu,
                memoryMiB,
                memoryLimitMiB: memoryMiB,
                // Default-deny outbound internet (or the configured allowlist).
                ...resolveEgressOpts(this.opts.outboundCidrAllowlist),
                tags: {
                    posthog_session_id: opts.sessionId,
                    posthog_team_id: String(opts.teamId),
                },
                // `verbose: true` plumbs Modal's provision-side logs into
                // gRPC responses — the SDK surfaces them on failure via the
                // error's `.message`, so a wedged image pull / scheduling
                // failure shows up in our catch block below instead of as
                // a silent timeout.
                verbose: true,
            })
        } catch (err) {
            // Provision-time failure. Log diagnostics and rethrow so the
            // worker can mark the sandbox row failed with a useful message.
            log.error(
                {
                    sessionId: opts.sessionId,
                    err: (err as Error).message,
                    stack: (err as Error).stack,
                    image: this.opts.image ?? DEFAULT_IMAGE_TAG,
                    region,
                    cpu,
                    memoryMiB,
                    timeoutMs,
                },
                'modal.sandbox.provision_failed'
            )
            throw err
        }

        try {
            // Per-session bits only — the canonical sandbox-host image bakes
            // `/sandbox/dispatch.js` and `/sandbox/host.js`. If someone
            // points us at a vanilla node base image they'll see ENOENT on
            // dispatch — by design; the image is the contract.
            await handle.filesystem.makeDirectory('/workdir')
            await handle.filesystem.makeDirectory('/workdir/tools')
            for (const tool of opts.tools) {
                const dir = `/workdir/tools/${tool.id}`
                await handle.filesystem.makeDirectory(dir)
                await handle.filesystem.writeText(tool.compiledJs, `${dir}/compiled.js`)
                await handle.filesystem.writeText(JSON.stringify(tool.schemaJson), `${dir}/schema.json`)
            }
            await handle.filesystem.writeText(JSON.stringify(opts.nonces), '/workdir/nonces.json')
        } catch (err) {
            // Tear down a half-built sandbox so we don't leak compute.
            await handle.terminate().catch(() => undefined)
            throw err
        }

        log.info(
            {
                sessionId: opts.sessionId,
                sandboxId: handle.sandboxId,
                name: sandboxName,
                region,
                cpu,
                memoryMiB,
                tools: opts.tools.length,
                timeoutMs,
            },
            'modal.sandbox.acquired'
        )

        const sandbox = new ModalSandbox({
            sessionId: opts.sessionId,
            handle,
            toolIds: new Set(opts.tools.map((t) => t.id)),
            invokeCounter: 0,
        })
        this.bySession.set(opts.sessionId, sandbox)
        return sandbox
    }

    async release(sessionId: string): Promise<void> {
        const s = this.bySession.get(sessionId)
        if (s) {
            await s.destroy()
            this.bySession.delete(sessionId)
        }
    }
}
