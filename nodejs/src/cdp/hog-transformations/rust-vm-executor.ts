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
    public async execute(
        invocation: CyclotronJobInvocationHogFunction,
        sensitiveValues: string[]
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null> {
        const module_ = this.getModule()
        if (!module_) {
            rustVmExecution.inc({ outcome: 'fallback_unavailable' })
            return null
        }

        let rust
        try {
            ;[rust] = await module_.executeBatch(invocation.hogFunction.bytecode, [invocation.state.globals], {
                maxSteps: RUST_MAX_STEPS,
            })
        } catch (error) {
            // A throw here is the FFI boundary, not the program — e.g. globals containing NaN or
            // Infinity, which serde_json can't represent. The Node VM takes the JS objects
            // directly and can run these, so fall back rather than fail the transformation.
            rustVmExecution.inc({ outcome: 'fallback_exception' })
            logger.warn('🦀', 'Rust HogVM invocation threw, falling back to the node vm', {
                functionId: invocation.functionId,
                teamId: invocation.teamId,
                error: String(error),
            })
            return null
        }
        if (!rust) {
            rustVmExecution.inc({ outcome: 'fallback_unavailable' })
            return null
        }

        if (rust.error && isUnsupportedByRustVm(rust.error)) {
            rustVmExecution.inc({ outcome: 'fallback_unsupported' })
            return null
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
