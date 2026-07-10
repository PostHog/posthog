import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createAddLogFunction, sanitizeLogMessage } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { HogvmNodeModule, RUST_MAX_STEPS, isUnsupportedByRustVm, loadHogvmNodeModule } from './rust-vm'

/**
 * Executes transformation invocations on the Rust HogVM (via the `@posthog/hogvm-node` napi
 * addon) as the primary executor, producing the same `CyclotronJobInvocationResult` shape the
 * Node executor does. Invocations the Rust VM can't run — the addon isn't built, or the program
 * calls a host function the binding doesn't implement — return null so the caller falls back to
 * the Node VM.
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

export class RustVmExecutor {
    constructor(private options: { mmdbPath: string }) {}

    private getModule(): HogvmNodeModule | null {
        return loadHogvmNodeModule({ mmdbPath: this.options.mmdbPath })
    }

    /**
     * Execute one transformation invocation on the Rust VM. Returns null when the Node VM must
     * run it instead.
     *
     * Runs through `executeBatch` (a napi AsyncTask on the libuv worker pool), NOT `executeSync`:
     * the step budget bounds total work, but a costly program running synchronously would
     * monopolize the ingestion worker's JS thread, bypassing the wall-clock limiting and
     * event-loop yielding the Node path has. Concurrent events therefore execute in parallel on
     * worker threads; batching many events into one call (rayon fan-out) is a possible follow-up.
     */
    /**
     * Count and log a fallback so every node-vm handoff is attributable to a function. Returns
     * null for the caller to pass through.
     */
    private fallback(
        outcome: 'fallback_unsupported' | 'fallback_exception' | 'fallback_empty_result',
        invocation: CyclotronJobInvocationHogFunction,
        error: unknown
    ): null {
        rustVmExecution.inc({ outcome })
        logger.warn('🦀', 'Rust HogVM invocation fell back to the node vm', {
            outcome,
            functionId: invocation.functionId,
            teamId: invocation.teamId,
            error: error !== undefined ? String(error) : undefined,
        })
        return null
    }

    public async execute(
        invocation: CyclotronJobInvocationHogFunction,
        sensitiveValues: string[]
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null> {
        const module_ = this.getModule()
        if (!module_) {
            // No per-invocation log: a missing addon affects every invocation and the loader
            // already warned once with the load error.
            rustVmExecution.inc({ outcome: 'fallback_unavailable' })
            return null
        }

        let rust
        try {
            ;[rust] = await module_.executeBatch(invocation.hogFunction.bytecode, [invocation.state.globals], {
                maxSteps: RUST_MAX_STEPS,
            })
        } catch (error) {
            // A throw here is the boundary or the native side, not the program's own error path —
            // marshalling failures (e.g. globals containing NaN or Infinity, which serde_json
            // can't represent), rust panics, addon bugs. Deliberately broad: the node vm can run
            // all of these, so correctness wins and the invocation falls back — while the warn log
            // and the fallback_exception outcome carry the error so native faults stay visible
            // rather than being silently healed.
            return this.fallback('fallback_exception', invocation, error)
        }
        if (!rust) {
            return this.fallback('fallback_empty_result', invocation, undefined)
        }

        if (rust.error && isUnsupportedByRustVm(rust.error)) {
            return this.fallback('fallback_unsupported', invocation, rust.error)
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
