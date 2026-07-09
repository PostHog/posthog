import { logger } from '~/common/utils/logger'

import { KNOWN_BOT_IP_LIST, KNOWN_BOT_UA_LIST } from './bots/bots'

/**
 * Shared access to the `@posthog/hogvm-node` napi addon (the Rust HogVM). The addon is optional —
 * when it isn't built for this environment, `loadHogvmNodeModule` returns null and callers fall
 * back to the Node VM.
 */

// The Rust VM budgets steps, not wall-clock time; generous so it never trips before the Node VM's
// timeout would.
export const RUST_MAX_STEPS = 1_000_000

export interface RustExecResult {
    result?: unknown
    error?: string
    durationUs: number
    /** Messages from print() calls, in call order, capped at 24 entries. */
    logs?: string[]
    /** True when print() was called past the cap and messages were dropped. */
    logsTruncated?: boolean
}

export interface HogvmNodeModule {
    init(options: { mmdbPath?: string; knownBotUaList?: string[]; knownBotIpList?: string[] }): void
    executeBatch(
        program: unknown[],
        events: unknown[],
        options?: { parallel?: boolean; maxSteps?: number }
    ): Promise<RustExecResult[]>
    executeSync(program: unknown[], globals: unknown, options?: { maxSteps?: number }): RustExecResult
}

let cachedModule: HogvmNodeModule | null | undefined = undefined

/**
 * Load and initialize the native addon once per process (`init` is idempotent on the Rust side).
 * Returns null when the addon isn't built for this environment.
 */
export function loadHogvmNodeModule(options: { mmdbPath: string }): HogvmNodeModule | null {
    if (cachedModule !== undefined) {
        return cachedModule
    }
    try {
        const module_: HogvmNodeModule = require('@posthog/hogvm-node')
        module_.init({
            mmdbPath: options.mmdbPath,
            knownBotUaList: KNOWN_BOT_UA_LIST,
            knownBotIpList: KNOWN_BOT_IP_LIST,
        })
        cachedModule = module_
    } catch (error) {
        cachedModule = null
        logger.warn('🦀', 'Rust HogVM native module unavailable', { error: String(error) })
    }
    return cachedModule
}

export function resetHogvmNodeModuleCacheForTests(): void {
    cachedModule = undefined
}
