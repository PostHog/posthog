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

// Error formats that mean "the Rust VM can't run this program" rather than "the program failed".
// All three are contracts with the Rust side, pinned by tests there — don't change one without the
// other: the binding's ext_fns fail unimplemented host functions with the `unsupported_ext_fn:`
// prefix (rust/common/hogvm/node/src/ext_fns.rs `unsupported()`); the hogvm crate reports calls to
// functions it doesn't know at all as `Unknown function <name>` and unresolvable global chains as
// `Unknown Global <chain>`.
export const UNSUPPORTED_EXT_FN_ERROR = 'unsupported_ext_fn:'
export const UNKNOWN_FUNCTION_ERROR_PREFIX = 'Unknown function '
export const UNKNOWN_GLOBAL_ERROR_PREFIX = 'Unknown Global '

/**
 * True when the error means the Rust VM can't run this program (the Node VM can). The executor
 * uses this to hand the invocation to the Node VM. Real execution errors must never match — the
 * caller would otherwise run the program twice.
 */
export function isUnsupportedByRustVm(error: string): boolean {
    return (
        error.includes(UNSUPPORTED_EXT_FN_ERROR) ||
        error.startsWith(UNKNOWN_FUNCTION_ERROR_PREFIX) ||
        error.startsWith(UNKNOWN_GLOBAL_ERROR_PREFIX)
    )
}

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
    executeSync(program: unknown[], globals: unknown, options?: { maxSteps?: number }): RustExecResult
}

let cachedModule: HogvmNodeModule | null | undefined = undefined

/**
 * Load and initialize the native addon once per process (`init` is idempotent on the Rust side).
 * Returns null when the addon isn't built for this environment. `options` only take effect on the
 * first call in the process — later callers always get the module as first configured.
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
