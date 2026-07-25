import { readFileSync } from 'node:fs'
import { availableParallelism } from 'node:os'

import { numFromEnv } from './env.ts'

/** Max threads a single ONNX session may use. Matches the ceiling numFromEnv enforces below. */
const ORT_THREADS_MAX = 32

/**
 * Intra-op threads for every ONNX session, defined once so the three models cannot drift apart.
 *
 * The default is clamped because `numFromEnv` validates the default as strictly as an env override:
 * an unclamped `containerCores()` above the ceiling would throw at module load and refuse to start
 * the sidecar, which is reachable whenever there is no quota to read and the host is large.
 *
 * Sized to the whole allotment because onnxruntime-node's `run` is synchronous, so inferences cannot
 * overlap and exactly one is ever executing. Divide this by the number of inference threads if that
 * ever stops being true, or the sessions will oversubscribe each other.
 */
export const ORT_THREADS = numFromEnv('ORT_THREADS', Math.min(ORT_THREADS_MAX, containerCores()), 1, ORT_THREADS_MAX)

/**
 * Cores this process may actually use, as opposed to the ones it can see.
 *
 * `availableParallelism()` reports the host's CPUs and knows nothing about the cgroup quota, so a
 * container limited to 4 cores on a 96-core node reports 96. Sizing a thread pool off that number
 * oversubscribes by an order of magnitude, which costs more in context switching than the threads
 * ever return. Read the quota the kernel enforces instead, and fall back only when there isn't one.
 */
export function containerCores(): number {
    // cgroup v2: "<quota> <period>", or "max <period>" when uncapped.
    try {
        const [quota, period] = readFileSync('/sys/fs/cgroup/cpu.max', 'utf8').trim().split(/\s+/)
        if (quota !== 'max') {
            return clampCores(Number(quota) / Number(period))
        }
    } catch {
        // not cgroup v2, or not containerised
    }
    // cgroup v1: a negative quota means uncapped.
    try {
        const quota = Number(readFileSync('/sys/fs/cgroup/cpu/cpu.cfs_quota_us', 'utf8'))
        const period = Number(readFileSync('/sys/fs/cgroup/cpu/cpu.cfs_period_us', 'utf8'))
        if (quota > 0 && period > 0) {
            return clampCores(quota / period)
        }
    } catch {
        // not cgroup v1, or not containerised
    }
    return availableParallelism()
}

/** Floors so a fractional quota never yields more threads than the quota allows: exceeding it is
 *  paid back as CFS throttling, which is the cost this sizing exists to avoid. */
function clampCores(cores: number): number {
    return Number.isFinite(cores) ? Math.max(1, Math.floor(cores)) : availableParallelism()
}
