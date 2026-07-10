import { Counter, Histogram } from 'prom-client'

import { HogBytecode } from '~/cdp/types'
import { logger } from '~/common/utils/logger'

/**
 * Shadow-executes sampled filter evaluations on the Rust HogVM (via the `@posthog/hogvm-node` napi
 * addon) to compare latency and correctness against the Node VM the CDP events consumer uses to
 * find matching hog functions. Filters are pure Hog (no host functions), so there's no setup: for a
 * sampled filter run we hand the same bytecode + globals to the Rust VM off the JS event loop,
 * record how long each VM took, and compare the boolean match. The Node result stays authoritative
 * — nothing here can affect it, and every failure is swallowed into a metric or log.
 *
 * The native addon is optional — if it isn't built for this environment the shadow disables itself.
 */

// The Rust VM budgets steps, not wall-clock time; generous so it never trips before the Node VM's
// timeout would.
const RUST_MAX_STEPS = 1_000_000

export const filterShadowDuration = new Histogram({
    name: 'hogvm_filter_shadow_duration_ms',
    help: 'Hog filter evaluation duration for shadow-sampled events, by VM',
    labelNames: ['vm'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100],
})

export const filterShadowComparison = new Counter({
    name: 'hogvm_filter_shadow_comparison_total',
    help: 'Outcomes of node-vs-rust hogvm filter shadow comparisons',
    labelNames: ['outcome'],
})

export type FilterShadowOutcome = 'match' | 'mismatch' | 'error'

interface RustExecResult {
    result?: unknown
    error?: string
    durationUs: number
}

interface HogvmNodeModule {
    executeBatch(
        program: unknown[],
        events: unknown[],
        options?: { parallel?: boolean; maxSteps?: number }
    ): Promise<RustExecResult[]>
}

/** A filter matches only when the program returns boolean true, mirroring the Node filtering logic. */
function rustFilterMatch(result: unknown): boolean {
    return result === true
}

export function classifyFilterShadowOutcome(nodeMatch: boolean, rust: RustExecResult | undefined): FilterShadowOutcome {
    if (!rust || rust.error) {
        return 'error'
    }
    return rustFilterMatch(rust.result) === nodeMatch ? 'match' : 'mismatch'
}

/**
 * The hook the shared filtering utility depends on. Kept as a narrow interface so
 * `filterFunctionInstrumented` doesn't import the whole service (and so tests can pass a stub).
 * Only the CDP events pipeline wires a real one in; every other caller leaves it undefined, so
 * nothing is compared.
 */
export interface FilterShadowCapturer {
    compare(bytecode: HogBytecode, globals: object, nodeMatch: boolean, nodeDurationMs: number): Promise<void>
}

export class RustVmFilterShadow implements FilterShadowCapturer {
    private module_: HogvmNodeModule | null | undefined = undefined

    constructor(private options: { sampleRate: number }) {}

    /**
     * For the sampled fraction of filter runs, execute the same bytecode + globals on the Rust VM
     * (off the JS event loop) and compare against the Node result. Fire-and-forget: callers don't
     * await it, and it never throws — failures become the `error` outcome.
     */
    public async compare(
        bytecode: HogBytecode,
        globals: object,
        nodeMatch: boolean,
        nodeDurationMs: number
    ): Promise<void> {
        if (this.options.sampleRate <= 0 || Math.random() >= this.options.sampleRate) {
            return
        }
        const module_ = this.getModule()
        if (!module_) {
            return
        }

        filterShadowDuration.observe({ vm: 'node' }, nodeDurationMs)
        try {
            const [rust] = await module_.executeBatch(bytecode, [globals], { maxSteps: RUST_MAX_STEPS })
            if (rust && !rust.error) {
                filterShadowDuration.observe({ vm: 'rust' }, rust.durationUs / 1000)
            }
            const outcome = classifyFilterShadowOutcome(nodeMatch, rust)
            filterShadowComparison.inc({ outcome })
            if (outcome === 'mismatch') {
                logger.warn('🦀', 'Rust HogVM filter shadow divergence', {
                    nodeMatch,
                    rustResult: rust?.result,
                })
            }
        } catch (error) {
            filterShadowComparison.inc({ outcome: 'error' })
            logger.warn('🦀', 'Rust HogVM filter shadow failed', { error: String(error) })
        }
    }

    private getModule(): HogvmNodeModule | null {
        if (this.module_ !== undefined) {
            return this.module_
        }
        try {
            this.module_ = require('@posthog/hogvm-node') as HogvmNodeModule
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
