import { readFileSync } from 'node:fs'
import { availableParallelism } from 'node:os'

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

/** Rounds rather than floors so a fractional limit still yields the cores it mostly has. */
function clampCores(cores: number): number {
    return Number.isFinite(cores) ? Math.max(1, Math.round(cores)) : availableParallelism()
}
