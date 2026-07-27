/**
 * In-process sandbox. No isolation. Used by tests and local-dev quick-start.
 *
 * Loads each tool's compiled.js into a fresh vm.Context, calls the exported
 * `defineTool({ id, actions })` to obtain the action map, then dispatches
 * `invoke` calls directly. Egress is unrestricted — production isolation +
 * outbound filtering live in the Modal sandbox + the cluster's smokescreen.
 */

import * as vm from 'vm'

import { HttpClient, type HttpFetcher } from '../runtime/http-client'
import { AcquireOpts, InvokeRequest, InvokeResponse, Sandbox, SandboxPool, SandboxToolLoad } from './sandbox'

interface LoadedAction {
    run: (args: unknown, ctx: SandboxToolRuntimeContext) => unknown | Promise<unknown>
}

interface LoadedTool {
    id: string
    actions: Record<string, LoadedAction>
}

export interface SandboxToolRuntimeContext {
    secrets: {
        ref: (name: string) => string
        value: (name: string) => string
    }
    http: {
        fetch: (url: string, init?: RequestInit) => Promise<Response>
    }
}

interface InProcessSandboxOpts {
    sessionId: string
    teamId: number
    tools: SandboxToolLoad[]
    nonces: Record<string, string>
    /** Optional plaintext secret resolution for `secrets.value()` (escape hatch). */
    secretValues?: Record<string, string>
    /** Outbound HTTP — same dispatcher native tools use. Falls back to direct fetch when omitted. */
    http?: HttpFetcher
}

class InProcessSandbox implements Sandbox {
    private alive = true
    private readonly tools: Map<string, LoadedTool>
    private readonly nonces: Record<string, string>
    private readonly secretValues: Record<string, string>
    private readonly http: HttpFetcher
    readonly sessionId: string

    constructor(opts: InProcessSandboxOpts) {
        this.sessionId = opts.sessionId
        this.nonces = opts.nonces
        this.secretValues = opts.secretValues ?? {}
        this.http = opts.http ?? new HttpClient()
        this.tools = new Map(opts.tools.map((t) => [t.id, this.loadTool(t)]))
    }

    /** No provider-side handle; reuse sessionId so the row column is non-empty. */
    get providerSandboxId(): string {
        return this.sessionId
    }

    private loadTool(load: SandboxToolLoad): LoadedTool {
        const guestFetch = (url: string, init?: RequestInit): Promise<Response> => this.http.fetch(url, init)
        const sandbox: Record<string, unknown> = {
            module: { exports: {} },
            exports: {},
            console,
            setTimeout,
            clearTimeout,
            setInterval,
            clearInterval,
            Promise,
            URL,
            URLSearchParams,
            TextEncoder,
            TextDecoder,
            Buffer,
            JSON,
            fetch: guestFetch,
        }
        sandbox.global = sandbox
        const ctx = vm.createContext(sandbox)
        try {
            vm.runInContext(load.compiledJs, ctx, { filename: `tools/${load.id}/compiled.js` })
        } catch (err) {
            throw new Error(`failed to load tool ${load.id}: ${(err as Error).message}`)
        }
        const moduleExports = (sandbox.module as { exports: unknown }).exports
        const exported = (moduleExports as { default?: unknown }).default ?? moduleExports
        const tool = this.coerceTool(load.id, exported)
        return tool
    }

    private coerceTool(id: string, exported: unknown): LoadedTool {
        if (!exported || typeof exported !== 'object') {
            throw new Error(`tool ${id} did not export an object`)
        }
        const obj = exported as { id?: string; actions?: Record<string, unknown> }
        if (!obj.actions || typeof obj.actions !== 'object') {
            throw new Error(`tool ${id} did not export an actions map`)
        }
        const actions: Record<string, LoadedAction> = {}
        for (const [name, fn] of Object.entries(obj.actions)) {
            if (typeof fn !== 'function') {
                throw new Error(`tool ${id} action ${name} is not a function`)
            }
            actions[name] = { run: fn as LoadedAction['run'] }
        }
        return { id: obj.id ?? id, actions }
    }

    private buildContext(): SandboxToolRuntimeContext {
        return {
            secrets: {
                ref: (name) => {
                    const n = this.nonces[name]
                    if (!n) {
                        throw new Error(`secret not bound: ${name}`)
                    }
                    return n
                },
                value: (name) => {
                    const v = this.secretValues[name]
                    if (v === undefined) {
                        throw new Error(`secret value not available: ${name}`)
                    }
                    return v
                },
            },
            http: {
                fetch: (url: string, init?: RequestInit) => this.http.fetch(url, init),
            },
        }
    }

    async invoke(req: InvokeRequest): Promise<InvokeResponse> {
        if (!this.alive) {
            return { ok: false, error: { code: 'sandbox_released', message: 'sandbox already released' } }
        }
        const tool = this.tools.get(req.toolId)
        if (!tool) {
            return { ok: false, error: { code: 'tool_not_loaded', message: `tool ${req.toolId} not loaded` } }
        }
        const action = tool.actions[req.action]
        if (!action) {
            return {
                ok: false,
                error: { code: 'action_not_found', message: `tool ${req.toolId} has no action ${req.action}` },
            }
        }
        const ctx = this.buildContext()
        try {
            const timeoutMs = req.timeoutMs ?? 30_000
            const result = await Promise.race([
                Promise.resolve(action.run(req.args, ctx)),
                new Promise<never>((_, rej) => setTimeout(() => rej(new Error('tool_timeout')), timeoutMs)),
            ])
            return { ok: true, result }
        } catch (err) {
            const e = err as Error
            return {
                ok: false,
                error: { code: e.message === 'tool_timeout' ? 'timeout' : 'exception', message: e.message },
            }
        }
    }

    async isAlive(): Promise<boolean> {
        return this.alive
    }

    async destroy(): Promise<void> {
        this.alive = false
    }
}

export class InProcessSandboxPool implements SandboxPool {
    readonly kind = 'in-process' as const
    private readonly bySession = new Map<string, InProcessSandbox>()
    private readonly secretValuesProvider?: (sessionId: string) => Record<string, string>
    private readonly http?: HttpFetcher

    constructor(opts?: {
        secretValuesProvider?: (sessionId: string) => Record<string, string>
        /** Outbound HTTP dispatcher for guest tool code (`fetch` + `ctx.http.fetch`). */
        http?: HttpFetcher
    }) {
        // Test-only. Guest code runs in this process — there's no isolation, so
        // a misbehaving sandbox can read process memory, write the local fs, or
        // exhaust CPU. Production uses `DockerSandboxPool` (local) or
        // `ModalSandboxPool` (prod), selected via `selectSandboxPool` from env.
        // Vitest sets NODE_ENV=test automatically; any direct construction
        // outside that env is a wiring mistake and we'd rather fail at boot
        // than silently run unsandboxed in dev or prod.
        if (process.env.NODE_ENV !== 'test') {
            throw new Error(
                `InProcessSandboxPool is test-only and refuses to construct when NODE_ENV !== 'test' (got ${
                    process.env.NODE_ENV === undefined ? '(unset)' : JSON.stringify(process.env.NODE_ENV)
                }). Use selectSandboxPool() to wire docker or modal.`
            )
        }
        this.secretValuesProvider = opts?.secretValuesProvider
        this.http = opts?.http
    }

    async acquireForSession(opts: AcquireOpts): Promise<Sandbox> {
        const existing = this.bySession.get(opts.sessionId)
        if (existing && (await existing.isAlive())) {
            return existing
        }
        const sandbox = new InProcessSandbox({
            sessionId: opts.sessionId,
            teamId: opts.teamId,
            tools: opts.tools,
            nonces: opts.nonces,
            secretValues: this.secretValuesProvider ? this.secretValuesProvider(opts.sessionId) : {},
            http: this.http,
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
