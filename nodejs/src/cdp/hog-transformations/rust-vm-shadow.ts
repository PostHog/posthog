import deepEqual from 'fast-deep-equal'
import { Counter, Histogram } from 'prom-client'

import { HogBytecode } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { KNOWN_BOT_IP_LIST, KNOWN_BOT_UA_LIST } from './bots/bots'

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

// The Rust VM budgets steps, not wall-clock time; generous so it never trips before the Node VM's
// timeout would.
const RUST_MAX_STEPS = 1_000_000
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

export type ShadowOutcome = 'match' | 'result_mismatch' | 'status_mismatch' | 'rust_error' | 'skipped_unsupported'

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

interface RustExecResult {
    result?: unknown
    error?: string
    durationUs: number
}

interface HogvmNodeModule {
    init(options: { mmdbPath?: string; knownBotUaList?: string[]; knownBotIpList?: string[] }): void
    executeBatch(
        program: unknown[],
        events: unknown[],
        options?: { parallel?: boolean; maxSteps?: number }
    ): Promise<RustExecResult[]>
}

export function classifyShadowOutcome(node: ShadowNodeResult, rust: RustExecResult | undefined): ShadowOutcome {
    if (!rust) {
        return 'rust_error'
    }
    if (rust.error) {
        // Host functions the rust binding doesn't implement — not comparable, not a divergence.
        if (rust.error.includes('unsupported_ext_fn:') || rust.error.includes('Unknown Global')) {
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
        if (this.buffer.length >= MAX_BUFFER_SIZE) {
            shadowComparison.inc({ outcome: 'rust_error' })
            return
        }
        this.buffer.push(item)
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

        shadowFlushSize.observe({ scope: 'flush' }, items.length)

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
        try {
            const module_: HogvmNodeModule = require('@posthog/hogvm-node')
            module_.init({
                mmdbPath: this.options.mmdbPath,
                knownBotUaList: KNOWN_BOT_UA_LIST,
                knownBotIpList: KNOWN_BOT_IP_LIST,
            })
            this.module_ = module_
            logger.info('🦀', 'Rust HogVM shadow mode enabled', { sampleRate: this.options.sampleRate })
        } catch (error) {
            this.module_ = null
            logger.warn('🦀', 'Rust HogVM native module unavailable, shadow mode disabled', {
                error: String(error),
            })
        }
        return this.module_
    }
}
