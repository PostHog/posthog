import { Counter, Histogram } from 'prom-client'

import { HogBytecode } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { KNOWN_BOT_IP_LIST, KNOWN_BOT_UA_LIST } from '../hog-transformations/bots/bots'

/**
 * Shadow-executes sampled filter (bytecode) evaluations on the Rust HogVM (via the
 * `@posthog/hogvm-node` napi addon) to compare latency and correctness against the Node VM used by
 * the CDP events consumer to find matching hog functions. The Node result stays authoritative:
 * captures buffer in memory and execute per batch off the hot path, results are discarded after
 * comparison, and any failure only surfaces as a metric or log.
 *
 * The real win from the Rust VM is that a batch of events sharing the same filter bytecode can be
 * fanned out over a rayon thread pool, so the flush groups by bytecode and executes each group as a
 * single parallel batch.
 *
 * The native addon is optional — if it isn't built for this environment the shadow disables itself.
 */

// The Rust VM budgets steps, not wall-clock time; generous so it never trips before the Node VM's
// timeout would.
const RUST_MAX_STEPS = 1_000_000
// STL functions whose output legitimately differs between two executions — filters using relative
// dates (now/today) are common, so programs calling them can never be compared and are skipped at
// capture time.
const NONDETERMINISTIC_FNS = new Set(['randomFloat', 'generateUUIDv4', 'now', 'today'])
const CALL_GLOBAL_OP = 2
// Safety cap so a stalled flush can't grow the buffer unboundedly.
const MAX_BUFFER_SIZE = 10_000

export const filterShadowExecutionDuration = new Histogram({
    name: 'hogvm_filter_shadow_execution_duration_ms',
    help: 'Per-invocation hog filter execution duration for shadow-sampled events, by VM',
    labelNames: ['vm'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100],
})

export const filterShadowBatchDuration = new Histogram({
    name: 'hogvm_filter_shadow_batch_duration_ms',
    help: 'Wall time of one rust executeBatch napi call for filters, marshalling included',
    buckets: [0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500],
})

export const filterShadowFlushSize = new Histogram({
    name: 'hogvm_filter_shadow_flush_invocations',
    help: 'Captured filter invocations per shadow flush (scope=flush) and per bytecode group within it (scope=bytecode) — group size is what the rayon fan-out sees',
    labelNames: ['scope'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
})

export const filterShadowComparison = new Counter({
    name: 'hogvm_filter_shadow_comparison_total',
    help: 'Outcomes of node-vs-rust hogvm filter shadow comparisons',
    labelNames: ['outcome'],
})

export type FilterShadowOutcome =
    | 'match'
    | 'result_mismatch'
    | 'status_mismatch'
    | 'rust_error'
    | 'skipped_unsupported'
    | 'skipped_nondeterministic'
    | 'dropped'

export interface FilterShadowNodeResult {
    /** Whether the Node filter matched (bytecode returned boolean true). */
    match: boolean
    /** Set when the Node VM threw while evaluating the filter. */
    error?: string
    durationMs: number
}

export interface FilterShadowCapturedInvocation {
    functionId: string
    teamId: number
    /** Same array reference across events for a given function+filter, so it groups the batch. */
    bytecode: HogBytecode
    /** Snapshot of the filter globals taken before the Node VM ran. */
    globalsJson: string
    node: FilterShadowNodeResult
}

/**
 * The subset of {@link RustVmFilterShadow} that the shared filtering utility depends on. Kept as a
 * narrow interface so `filterFunctionInstrumented` doesn't import the whole service (and so tests
 * can pass a stub). Only the CDP events pipeline wires a real one in; every other caller leaves it
 * undefined, so nothing is captured.
 */
export interface FilterShadowCapturer {
    shouldCapture(): boolean
    capture(item: FilterShadowCapturedInvocation): void
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

/** The Rust VM returns the raw program result; a filter matches only when it returns boolean true,
 * mirroring the Node filtering logic. */
function rustFilterMatch(result: unknown): boolean {
    return typeof result === 'boolean' && result
}

export function classifyFilterShadowOutcome(
    node: FilterShadowNodeResult,
    rust: RustExecResult | undefined
): FilterShadowOutcome {
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
        return node.error ? 'match' : 'status_mismatch'
    }
    if (node.error) {
        return 'status_mismatch'
    }
    return rustFilterMatch(rust.result) === node.match ? 'match' : 'result_mismatch'
}

export class RustVmFilterShadow {
    private buffer: FilterShadowCapturedInvocation[] = []
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

    public capture(item: FilterShadowCapturedInvocation): void {
        if (this.isNondeterministic(item.functionId, item.bytecode)) {
            filterShadowComparison.inc({ outcome: 'skipped_nondeterministic' })
            return
        }
        if (this.buffer.length >= MAX_BUFFER_SIZE) {
            filterShadowComparison.inc({ outcome: 'dropped' })
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
     * Execute everything captured since the last flush on the Rust VM and compare. Runs off the hot
     * path (fired from the events pipeline without being awaited); never throws.
     */
    public async flush(): Promise<void> {
        const items = this.buffer
        this.buffer = []
        const module_ = this.getModule()
        if (!module_ || items.length === 0) {
            return
        }

        // A previous flush's native batch may still be running on its worker threads. Never stack
        // batches: while one is in flight, drop this round.
        if (this.flushInFlight) {
            filterShadowComparison.inc({ outcome: 'dropped' }, items.length)
            return
        }
        this.flushInFlight = true

        filterShadowFlushSize.observe({ scope: 'flush' }, items.length)

        try {
            await this.executeAndCompare(items)
        } catch (error) {
            logger.warn('🦀', 'Rust HogVM filter shadow flush failed', { error: String(error) })
        } finally {
            this.flushInFlight = false
        }
    }

    private async executeAndCompare(items: FilterShadowCapturedInvocation[]): Promise<void> {
        const module_ = this.getModule()
        if (!module_) {
            return
        }

        // Group by bytecode reference: the hog function manager caches functions, so every event
        // that ran the same filter shares the exact same bytecode array. Each group runs as one
        // rust batch that fans its events out over rayon (`parallel: true`).
        const byBytecode = new Map<HogBytecode, FilterShadowCapturedInvocation[]>()
        for (const item of items) {
            const group = byBytecode.get(item.bytecode)
            if (group) {
                group.push(item)
            } else {
                byBytecode.set(item.bytecode, [item])
            }
        }

        // Run the groups concurrently, not one after another: each `executeBatch` is a napi
        // AsyncTask off the JS event loop, so distinct filters execute in parallel with each other
        // while every group also fans its own events out over rayon internally. This is where the
        // full parallelism the shadow is measuring actually happens.
        await Promise.all(
            Array.from(byBytecode.entries()).map(([bytecode, group]) => this.executeGroup(module_, bytecode, group))
        )
    }

    private async executeGroup(
        module_: HogvmNodeModule,
        bytecode: HogBytecode,
        group: FilterShadowCapturedInvocation[]
    ): Promise<void> {
        filterShadowFlushSize.observe({ scope: 'bytecode' }, group.length)
        let rustResults: RustExecResult[] = []
        const stopTimer = filterShadowBatchDuration.startTimer()
        try {
            rustResults = await module_.executeBatch(
                bytecode,
                group.map((item) => parseJSON(item.globalsJson)),
                { parallel: true, maxSteps: RUST_MAX_STEPS }
            )
        } catch (error) {
            logger.warn('🦀', 'Rust HogVM filter shadow batch failed', {
                functionId: group[0].functionId,
                error: String(error),
            })
        } finally {
            stopTimer()
        }

        let mismatchLogged = false
        group.forEach((item, index) => {
            const rust: RustExecResult | undefined = rustResults[index]
            filterShadowExecutionDuration.observe({ vm: 'node' }, item.node.durationMs)
            if (rust) {
                filterShadowExecutionDuration.observe({ vm: 'rust' }, rust.durationUs / 1000)
            }
            const outcome = classifyFilterShadowOutcome(item.node, rust)
            filterShadowComparison.inc({ outcome })
            // One example per bytecode group per flush is enough to identify a diverging filter
            // without flooding the logs; replay its bytecode offline for the actual diff.
            if ((outcome === 'result_mismatch' || outcome === 'status_mismatch') && !mismatchLogged) {
                mismatchLogged = true
                logger.warn('🦀', 'Rust HogVM filter shadow divergence', {
                    outcome,
                    functionId: item.functionId,
                    teamId: item.teamId,
                    nodeMatch: item.node.match,
                    nodeError: item.node.error,
                    rustResult: rust?.result,
                    rustError: rust?.error,
                })
            }
        })
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
            logger.info('🦀', 'Rust HogVM filter shadow mode enabled', { sampleRate: this.options.sampleRate })
        } catch (error) {
            this.module_ = null
            logger.warn('🦀', 'Rust HogVM native module unavailable, filter shadow mode disabled', {
                error: String(error),
            })
        }
        return this.module_
    }
}
