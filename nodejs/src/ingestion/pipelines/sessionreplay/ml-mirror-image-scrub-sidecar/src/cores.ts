import { readFileSync } from 'node:fs'
import { availableParallelism } from 'node:os'

import { numFromEnv } from './env.ts'

/** Max threads a single ONNX session may use. Matches the ceiling numFromEnv enforces below. */
const ORT_THREADS_MAX = 32

/** Assumed allotment when no quota is readable. Small on purpose: see the fallback in containerCores. */
const NO_QUOTA_CORES = 4

/** Enough to cover any pod this lane is deployed on; guards a bad env value from forking hundreds. */
const SCRUB_WORKERS_MAX = 32

/**
 * Inference worker threads, one per core by default.
 *
 * onnxruntime-node's `run` blocks the thread that calls it, so a single-threaded process can only
 * ever have one inference executing however many requests are in flight. A thread each is what
 * converts cores into concurrent scrubs.
 */
export const SCRUB_WORKERS = numFromEnv(
    'SCRUB_WORKERS',
    Math.min(SCRUB_WORKERS_MAX, containerCores()),
    1,
    SCRUB_WORKERS_MAX
)

/**
 * Intra-op threads for every ONNX session, defined once so the three models cannot drift apart.
 *
 * The default is clamped because `numFromEnv` validates the default as strictly as an env override:
 * an unclamped `containerCores()` above the ceiling would throw at module load and refuse to start
 * the sidecar, which is reachable whenever there is no quota to read and the host is large.
 *
 * Divided by the worker count because each worker runs its own inference concurrently with the
 * others, so the per-session pools multiply. Threads times workers is what has to fit the allotment:
 * exceeding it is paid back as CFS throttling, which is the cost this sizing exists to avoid.
 */
export const ORT_THREADS = numFromEnv(
    'ORT_THREADS',
    Math.min(ORT_THREADS_MAX, Math.max(1, Math.floor(containerCores() / SCRUB_WORKERS))),
    1,
    ORT_THREADS_MAX
)

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
