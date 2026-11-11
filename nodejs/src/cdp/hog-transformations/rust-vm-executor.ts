import { LRUCache } from 'lru-cache'
import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createAddLogFunction, sanitizeLogMessage } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import {
    HogvmNodeModule,
    MARSHAL_ERROR_PREFIX,
    RUST_MAX_STEPS,
    RustExecResult,
    isUnsupportedByRustVm,
    loadHogvmNodeModule,
    programKey,
} from './rust-vm'
import { RustVmBatchScheduler } from './rust-vm-batch-scheduler'

/**
 * Executes transformation invocations on the Rust HogVM (via the `@posthog/hogvm-node` napi
 * addon) as the primary executor, producing the same `CyclotronJobInvocationResult` shape the
 * Node executor does. Invocations the Rust VM can't run — the addon isn't built, or the program
 * calls a host function the binding doesn't implement — return null so the caller falls back to
 * the Node VM.
 *
 * Two execution paths: `execute` runs one invocation synchronously on the JS thread
 * (`executeRegisteredSync`); `executeBatched` enqueues into a {@link RustVmBatchScheduler} that
 * coalesces same-program invocations into one `executeRegisteredBatch` FFI crossing per tick,
 * executed off the JS event loop. Both execute a program the addon registered once per distinct
 * bytecode, so the per-event cost is the globals crossing, not re-marshalling and re-decoding.
 */

export const rustVmExecution = new Counter({
    name: 'hogvm_rust_execution_total',
    help: 'Outcomes of transformation executions where the Rust HogVM is the primary executor',
    labelNames: ['outcome'],
})

export const rustVmExecutionDuration = new Histogram({
    name: 'hogvm_rust_execution_duration_ms',
    help: 'Per-invocation hog execution duration on the Rust HogVM as the primary executor',
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100],
})

export const rustVmProgramRegistrations = new Counter({
    name: 'hogvm_rust_program_registrations_total',
    help: 'Programs registered with the Rust HogVM after a miss in the handle cache',
})

/** Bounds the Rust-side registry: one entry per distinct program, shared by every function with that bytecode. */
export const MAX_REGISTERED_PROGRAMS = 500

type RegistryBindings = Required<
    Pick<HogvmNodeModule, 'registerProgram' | 'releaseProgram' | 'executeRegisteredSync' | 'executeRegisteredBatch'>
>

export class RustVmExecutor {
    private scheduler: RustVmBatchScheduler

    /**
     * Handles by bytecode content: every team has its own hog function row, so one template arrives
     * as thousands of functions with identical bytecode and registers once. `dispose` is the single
     * owner of releasing handles, so no caller releases directly and no handle is released twice.
     */
    private handles: LRUCache<string, number>

    constructor(private options: { mmdbPath: string }) {
        this.scheduler = new RustVmBatchScheduler(async (bytecode, events) => {
            const module_ = this.getModule()
            if (!module_) {
                // Unreachable in practice: executeBatched checks the module before enqueueing.
                throw new Error('Rust HogVM native module unavailable')
            }
            const registry = this.registryOf(module_)
            if (!registry) {
                return module_.executeBatch(bytecode, events, { parallel: true, maxSteps: RUST_MAX_STEPS })
            }
            // Resolve the handle in the same synchronous span as the FFI call: `handleFor`
            // re-registers an evicted program, and nothing can release the handle before the call.
            const handle = this.handleFor(registry, bytecode)
            return registry.executeRegisteredBatch(handle, events, { parallel: true, maxSteps: RUST_MAX_STEPS })
        })
        this.handles = new LRUCache({
            max: MAX_REGISTERED_PROGRAMS,
            dispose: (handle) => this.getModule()?.releaseProgram?.(handle),
        })
    }

    private getModule(): HogvmNodeModule | null {
        return loadHogvmNodeModule({ mmdbPath: this.options.mmdbPath })
    }

    /**
     * All four registry bindings, or null when the addon predates them: it is built and shipped
     * separately from this code, and the caller then executes unregistered instead of throwing.
     */
    private registryOf(module_: HogvmNodeModule): RegistryBindings | null {
        const { registerProgram, releaseProgram, executeRegisteredSync, executeRegisteredBatch } = module_
        if (!registerProgram || !releaseProgram || !executeRegisteredSync || !executeRegisteredBatch) {
            return null
        }
        return { registerProgram, releaseProgram, executeRegisteredSync, executeRegisteredBatch }
    }

    private handleFor(registry: RegistryBindings, bytecode: unknown[]): number {
        const key = programKey(bytecode)
        const cached = this.handles.get(key)
        if (cached !== undefined) {
            return cached
        }

        rustVmProgramRegistrations.inc()
        const handle = registry.registerProgram(bytecode)
        this.handles.set(key, handle)
        return handle
    }

    /**
     * Count and log a fallback so every node-vm handoff is attributable to a function. Returns
     * null for the caller to pass through.
     */
    private fallback(
        outcome: 'fallback_unsupported' | 'fallback_exception',
        invocation: CyclotronJobInvocationHogFunction,
        sensitiveValues: string[],
        error: unknown
    ): null {
        rustVmExecution.inc({ outcome })
        logger.warn('🦀', 'Rust HogVM invocation fell back to the node vm', {
            outcome,
            functionId: invocation.functionId,
            teamId: invocation.teamId,
            // Same redaction as hog print logs: marshalling errors and panic messages can embed
            // values from the invocation globals, which include secret inputs.
            error: error !== undefined ? sanitizeLogMessage([String(error)], sensitiveValues) : undefined,
        })
        return null
    }

    /**
     * Execute one transformation invocation on the Rust VM. Returns null when the Node VM must
     * run it instead.
     *
     * Runs through `executeRegisteredSync` on the JS thread — the same threading model as the Node VM's
     * exec, minus the work. Executions are sub-millisecond and bounded by the step budget, so a
     * libuv thread-hop per invocation would cost more than the execution it offloads.
     */
    public execute(
        invocation: CyclotronJobInvocationHogFunction,
        sensitiveValues: string[]
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null {
        const module_ = this.getModule()
        if (!module_) {
            // No per-invocation log: a missing addon affects every invocation and the loader
            // already warned once with the load error.
            rustVmExecution.inc({ outcome: 'fallback_unavailable' })
            return null
        }

        let rust
        try {
            const registry = this.registryOf(module_)
            rust = registry
                ? registry.executeRegisteredSync(
                      this.handleFor(registry, invocation.hogFunction.bytecode),
                      invocation.state.globals,
                      { maxSteps: RUST_MAX_STEPS }
                  )
                : module_.executeSync(invocation.hogFunction.bytecode, invocation.state.globals, {
                      maxSteps: RUST_MAX_STEPS,
                  })
        } catch (error) {
            // A throw here is the boundary or the native side, not the program's own error path —
            // marshalling failures (e.g. globals containing NaN or Infinity, which serde_json
            // can't represent), rust panics, addon bugs. Deliberately broad: the node vm can run
            // all of these, so correctness wins and the invocation falls back — while the warn log
            // and the fallback_exception outcome carry the error so native faults stay visible
            // rather than being silently healed.
            return this.fallback('fallback_exception', invocation, sensitiveValues, error)
        }

        return this.toInvocationResult(rust, invocation, sensitiveValues)
    }

    /**
     * Execute one transformation invocation via the batching scheduler: same-program invocations
     * in flight during the same tick share one `executeRegisteredBatch` call, off the JS event loop.
     * Returns null when the Node VM must run it instead — same fallback contract as `execute`,
     * with a batch event that failed JS→JSON conversion (`marshal_error:`) treated like the sync
     * path's boundary throw: that event alone falls back, having never executed.
     */
    public async executeBatched(
        invocation: CyclotronJobInvocationHogFunction,
        sensitiveValues: string[]
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null> {
        const module_ = this.getModule()
        if (!module_) {
            rustVmExecution.inc({ outcome: 'fallback_unavailable' })
            return null
        }

        let rust: RustExecResult
        try {
            rust = await this.scheduler.execute(invocation.hogFunction.bytecode, invocation.state.globals)
        } catch (error) {
            // A rejected batch never delivered results, so nothing executed — safe to fall back.
            return this.fallback('fallback_exception', invocation, sensitiveValues, error)
        }

        if (rust.error?.startsWith(MARSHAL_ERROR_PREFIX)) {
            return this.fallback('fallback_exception', invocation, sensitiveValues, rust.error)
        }

        return this.toInvocationResult(rust, invocation, sensitiveValues)
    }

    private toInvocationResult(
        rust: RustExecResult,
        invocation: CyclotronJobInvocationHogFunction,
        sensitiveValues: string[]
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null {
        if (rust.error && isUnsupportedByRustVm(rust.error)) {
            return this.fallback('fallback_unsupported', invocation, sensitiveValues, rust.error)
        }

        const durationMs = rust.durationUs / 1000
        rustVmExecutionDuration.observe(durationMs)

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation)
        const addLog = createAddLogFunction(result.logs)
        result.invocation.state.timings.push({ kind: 'hog', duration_ms: durationMs })

        const eventId = invocation.state.globals.event?.uuid || 'Unknown event'

        for (const message of rust.logs ?? []) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: sanitizeLogMessage([message], sensitiveValues),
            })
        }
        if (rust.logsTruncated) {
            addLog('warn', `Function exceeded maximum log entries. No more logs will be collected. Event: ${eventId}`)
        }

        if (rust.error) {
            rustVmExecution.inc({ outcome: 'error' })
            addLog('error', `Error executing function on event ${eventId}: ${rust.error}`)
            result.error = rust.error
            return result
        }

        rustVmExecution.inc({ outcome: 'executed' })
        if (rust.result) {
            result.execResult = rust.result
        }
        addLog('debug', `Function completed in ${Number(durationMs.toFixed(2))}ms.`)
        return result
    }
}
