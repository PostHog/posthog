import { readFileSync } from 'node:fs'
import { availableParallelism } from 'node:os'

import { numFromEnv } from './env.ts'

/** Max threads a single ONNX session may use. Matches the ceiling numFromEnv enforces below. */
const ORT_THREADS_MAX = 32

/** Assumed allotment when no quota is readable. Small on purpose: see the fallback in containerCores. */
const NO_QUOTA_CORES = 4

/**
 * Intra-op threads for every ONNX session, defined once so the three models cannot drift apart.
 *
 * The default is clamped because `numFromEnv` validates the default as strictly as an env override:
 * an unclamped `containerCores()` above the ceiling would throw at module load and refuse to start
 * the sidecar, which is reachable whenever there is no quota to read and the host is large.
 *
 * Sized to the whole allotment because onnxruntime-node's `run` is synchronous (verified against
 * v1.27.0: `js/node/lib/backend.ts` calls the native `run` inside `setImmediate`, and
 * `inference_session_wrap.h` declares only a `[sync]` Run), so inferences cannot overlap and exactly
 * one executes at a time. Divide this by the number of concurrent inferences if that stops being
 * true, whether by an upstream `RunAsync` or by moving inference onto worker threads.
 */
export const ORT_THREADS = numFromEnv('ORT_THREADS', Math.min(ORT_THREADS_MAX, containerCores()), 1, ORT_THREADS_MAX)

/**
 * Cores this process may actually use, as opposed to the ones it can see.
 *
 * `availableParallelism()` reports the host's CPUs and knows nothing about the cgroup quota, so a
 * container limited to 4 cores on a 96-core node reports 96. Sizing a thread pool off that number
 * oversubscribes by an order of magnitude, which costs more in context switching than the threads
 * ever return.
 */
export function containerCores(): number {
    const quota = quotaCores((path) => readFileSync(path, 'utf8'))
    if (quota !== null) {
        return quota
    }
    // Deliberately not availableParallelism(): a pod with CPU requests but no limit reads `max`, as
    // does any runtime sharing the host's cgroup namespace, and the host's core count is the very
    // number this exists to avoid. Guessing small costs some throughput on an uncapped pod; guessing
    // the host's size costs an order of magnitude of oversubscription on a capped one.
    return Math.min(NO_QUOTA_CORES, availableParallelism())
}

/**
 * The enforced quota in whole cores, or null when the kernel reports no cap. Takes its reader so the
 * parsing is testable without a cgroup filesystem, which is most of where this can go wrong: the
 * failure mode is a silently wrong thread count rather than an error.
 */
export function quotaCores(read: (path: string) => string): number | null {
    // cgroup v2: "<quota> <period>", or "max <period>" when uncapped.
    try {
        const [quota, period] = read('/sys/fs/cgroup/cpu.max').trim().split(/\s+/)
        if (quota !== 'max') {
            return wholeCores(Number(quota) / Number(period))
        }
    } catch {
        // not cgroup v2, or not containerised
    }
    // cgroup v1: a negative quota means uncapped.
    try {
        const quota = Number(read('/sys/fs/cgroup/cpu/cpu.cfs_quota_us'))
        const period = Number(read('/sys/fs/cgroup/cpu/cpu.cfs_period_us'))
        if (quota > 0 && period > 0) {
            return wholeCores(quota / period)
        }
    } catch {
        // not cgroup v1, or not containerised
    }
    return null
}

/** Floors so a fractional quota never yields more threads than the quota allows: exceeding it is
 *  paid back as CFS throttling, which is the cost this sizing exists to avoid. */
function wholeCores(cores: number): number | null {
    return Number.isFinite(cores) ? Math.max(1, Math.floor(cores)) : null
}
