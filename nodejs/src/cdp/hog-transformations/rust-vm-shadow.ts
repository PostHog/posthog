import deepEqual from 'fast-deep-equal'
import { Counter, Histogram } from 'prom-client'

import { HogBytecode } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HogvmNodeModule, RUST_MAX_STEPS, RustExecResult, loadHogvmNodeModule } from './rust-vm'

/**
 * Shadow-executes sampled transformation invocations on the Rust HogVM (via the
 * `@posthog/hogvm-node` napi addon) to compare latency and correctness against the Node VM. The
 * Node result stays authoritative: captures buffer in memory and execute per batch during the
 * transformer's flush, results are discarded after comparison, and any failure only surfaces as a
 * metric or log.
 *
 * The native addon is optional — if it isn't built for this environment the shadow disables
 * itself.
 */

// STL functions whose output legitimately differs between two executions — programs calling them
// can never be compared, so they're skipped at capture time.
const NONDETERMINISTIC_FNS = new Set(['randomFloat', 'generateUUIDv4', 'now', 'today'])
const CALL_GLOBAL_OP = 2
// Safety cap so a stalled flush can't grow the buffer unboundedly.
const MAX_BUFFER_SIZE = 10_000

export const shadowExecutionDuration = new Histogram({
    name: 'hogvm_shadow_execution_duration_ms',
    help: 'Per-invocation hog execution duration for shadow-sampled transformations, by VM',
    labelNames: ['vm'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100],
})

export const shadowBatchDuration = new Histogram({
    name: 'hogvm_shadow_batch_duration_ms',
    help: 'Wall time of one rust executeBatch napi call, marshalling included',
    buckets: [0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500],
})

export const shadowFlushSize = new Histogram({
    name: 'hogvm_shadow_flush_invocations',
    help: 'Captured invocations per shadow flush (scope=flush) and per function group within it (scope=function) — group size is what the rayon fan-out sees',
    labelNames: ['scope'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
})

export const shadowComparison = new Counter({
    name: 'hogvm_shadow_comparison_total',
    help: 'Outcomes of node-vs-rust hogvm shadow comparisons',
    labelNames: ['outcome'],
})

export type ShadowOutcome =
    | 'match'
    | 'result_mismatch'
    | 'status_mismatch'
    | 'rust_error'
    | 'skipped_unsupported'
    | 'skipped_nondeterministic'
    | 'dropped'

export interface ShadowNodeResult {
    finished: boolean
    error?: string
    /** JSON snapshot of execResult taken at capture time — the transformer mutates the live
     * object right after execution (bookkeeping properties, chained transformations). */
    execResultJson: string | null
    durationMs: number
}

export interface ShadowCapturedInvocation {
    functionId: string
    teamId: number
    bytecode: HogBytecode
    /** state.globals snapshot taken before the Node VM ran (later transformations mutate them). */
    globalsJson: string
    node: ShadowNodeResult
}

export function classifyShadowOutcome(node: ShadowNodeResult, rust: RustExecResult | undefined): ShadowOutcome {
    if (!rust) {
        return 'rust_error'
    }
    if (rust.error) {
        // Host functions the rust binding doesn't implement — not comparable, not a divergence.
        // 'Unknown Global <name>' is the rust VM's exact error for calling a function it doesn't
        // know; anchored to the prefix so other errors mentioning the words can't be swallowed.
        if (rust.error.includes('unsupported_ext_fn:') || rust.error.startsWith('Unknown Global ')) {
            return 'skipped_unsupported'
        }
        // Both VMs failed the program: they agree.
        return !node.finished || node.error ? 'match' : 'status_mismatch'
    }
    if (!node.finished || node.error) {
        return 'status_mismatch'
    }
    const nodeResult = node.execResultJson != null ? parseJSON(node.execResultJson) : null
    return deepEqual(nodeResult, rust.result ?? null) ? 'match' : 'result_mismatch'
}

export class RustVmShadow {
    private buffer: ShadowCapturedInvocation[] = []
    private module_: HogvmNodeModule | null | undefined = undefined
    private flushInFlight = false
    private nondeterministicByFunction = new Map<string, boolean>()

    constructor(
        private options: {
            sampleRate: number
            mmdbPath: string
        }
    ) {}

    /** True for the sampled fraction of invocations, and only when the native addon is loadable. */
    public shouldCapture(): boolean {
        if (this.options.sampleRate <= 0 || !this.getModule()) {
            return false
        }
        return Math.random() < this.options.sampleRate
    }

    public capture(item: ShadowCapturedInvocation): void {
        if (this.isNondeterministic(item.functionId, item.bytecode)) {
            shadowComparison.inc({ outcome: 'skipped_nondeterministic' })
            return
        }
        if (this.buffer.length >= MAX_BUFFER_SIZE) {
            shadowComparison.inc({ outcome: 'dropped' })
            return
        }
        this.buffer.push(item)
    }

    // Every string literal in hog bytecode is preceded by the STRING op (32); only CALL_GLOBAL (2)
    // is directly followed by the function name, so this pair scan cannot false-positive on string
    // literals that merely contain a function name.
    private isNondeterministic(functionId: string, bytecode: HogBytecode): boolean {
        let cached = this.nondeterministicByFunction.get(functionId)
        if (cached === undefined) {
            cached = bytecode.some(
                (token, index) =>
                    token === CALL_GLOBAL_OP &&
                    typeof bytecode[index + 1] === 'string' &&
                    NONDETERMINISTIC_FNS.has(bytecode[index + 1] as string)
            )
            if (this.nondeterministicByFunction.size >= MAX_BUFFER_SIZE) {
                this.nondeterministicByFunction.clear()
            }
            this.nondeterministicByFunction.set(functionId, cached)
        }
        return cached
    }

    /**
     * Execute everything captured since the last flush on the Rust VM and compare. Runs off the
     * hot path (the transformer's afterBatch drain); callers wrap it in `mirrorCall` so it can
     * never affect the primary pipeline.
     */
    public async flush(): Promise<void> {
        const items = this.buffer
        this.buffer = []
        const module_ = this.getModule()
        if (!module_ || items.length === 0) {
            return
        }

        // The caller's mirrorCall timeout only stops awaiting — the native batch keeps running on
        // its worker threads. Never stack batches: while one is in flight, drop new captures.
        if (this.flushInFlight) {
            shadowComparison.inc({ outcome: 'dropped' }, items.length)
            return
        }
        this.flushInFlight = true

        shadowFlushSize.observe({ scope: 'flush' }, items.length)

        try {
            await this.executeAndCompare(items)
        } finally {
            this.flushInFlight = false
        }
    }

    private async executeAndCompare(items: ShadowCapturedInvocation[]): Promise<void> {
        const module_ = this.getModule()
        if (!module_) {
            return
        }

        const byFunction = new Map<string, ShadowCapturedInvocation[]>()
        for (const item of items) {
            const group = byFunction.get(item.functionId)
            if (group) {
                group.push(item)
            } else {
                byFunction.set(item.functionId, [item])
            }
        }

        for (const group of byFunction.values()) {
            shadowFlushSize.observe({ scope: 'function' }, group.length)
            let rustResults: RustExecResult[] = []
            const stopTimer = shadowBatchDuration.startTimer()
            try {
                rustResults = await module_.executeBatch(
                    group[0].bytecode,
                    group.map((item) => parseJSON(item.globalsJson)),
                    { parallel: true, maxSteps: RUST_MAX_STEPS }
                )
            } catch (error) {
                logger.warn('🦀', 'Rust HogVM shadow batch failed', {
                    functionId: group[0].functionId,
                    error: String(error),
                })
            } finally {
                stopTimer()
            }

            let mismatchLogged = false
            group.forEach((item, index) => {
                const rust: RustExecResult | undefined = rustResults[index]
                shadowExecutionDuration.observe({ vm: 'node' }, item.node.durationMs)
                if (rust) {
                    shadowExecutionDuration.observe({ vm: 'rust' }, rust.durationUs / 1000)
                }
                const outcome = classifyShadowOutcome(item.node, rust)
                shadowComparison.inc({ outcome })
                // One example per function per flush is enough to identify a diverging function
                // without flooding the logs; replay its bytecode offline for the actual diff.
                if ((outcome === 'result_mismatch' || outcome === 'status_mismatch') && !mismatchLogged) {
                    mismatchLogged = true
                    logger.warn('🦀', 'Rust HogVM shadow divergence', {
                        outcome,
                        functionId: item.functionId,
                        teamId: item.teamId,
                        nodeError: item.node.error,
                        rustError: rust?.error,
                    })
                }
            })
        }
    }

    private getModule(): HogvmNodeModule | null {
        if (this.module_ !== undefined) {
            return this.module_
        }
        if (this.options.sampleRate <= 0) {
            this.module_ = null
            return null
        }
        this.module_ = loadHogvmNodeModule({ mmdbPath: this.options.mmdbPath })
        if (this.module_) {
            logger.info('🦀', 'Rust HogVM shadow mode enabled', { sampleRate: this.options.sampleRate })
        }
        return this.module_
    }
}
