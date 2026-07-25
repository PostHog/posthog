import { readFileSync } from 'node:fs'
import { availableParallelism, totalmem } from 'node:os'

import { numFromEnv } from './env.ts'

/** Max threads a single ONNX session may use. Matches the ceiling numFromEnv enforces below. */
const ORT_THREADS_MAX = 32

/** Assumed allotment when no quota is readable. Small on purpose: see the fallback in containerCores. */
const NO_QUOTA_CORES = 4

/** Enough to cover any pod this lane is deployed on; guards a bad env value from forking hundreds. */
const SCRUB_WORKERS_MAX = 32

/**
 * Memory to assume each worker needs: its own V8 isolate, three ONNX sessions with their arenas, a
 * zxing wasm instance, and the full-frame sharp buffers a scrub holds. Taken from the ratio the
 * deployed pod already runs at (4 cores to 2Gi in
 * charts/argocd/ingestion/config/ingestion-sessionreplay-ml-image-scrub.yaml), so on that shape it
 * changes nothing and only binds where cores outrun memory.
 */
const WORKER_MEMORY_BUDGET_BYTES = 512 * 1024 * 1024

/**
 * Inference worker threads, one per core by default, capped by the memory limit.
 *
 * onnxruntime-node's `run` blocks the thread that calls it, so a single-threaded process can only
 * ever have one inference executing however many requests are in flight. A thread each is what
 * converts cores into concurrent scrubs.
 *
 * Cores alone would oversubscribe memory on a node whose CPU-to-memory ratio is higher than the
 * pod's, and every worker's footprint is paid at startup while it loads its models: too many turns
 * a healthy pod into an OOM crash loop that never serves a request.
 */
export const SCRUB_WORKERS = numFromEnv(
    'SCRUB_WORKERS',
    Math.min(SCRUB_WORKERS_MAX, containerCores(), memoryBoundedWorkers()),
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
 * The default divides by the worker count because each worker runs its own inference concurrently
 * with the others, so the per-session pools multiply. Threads times workers is what has to fit the
 * allotment: exceeding it is paid back as CFS throttling, which is the cost this sizing exists to
 * avoid. An ORT_THREADS override is per session and is not divided, so it is a total only when
 * SCRUB_WORKERS is 1.
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

/** Workers the memory limit can hold, or SCRUB_WORKERS_MAX when there is no limit to read: an
 *  unreadable limit must not cap the pool below what the cores support. */
export function memoryBoundedWorkers(): number {
    const limit = memoryLimitBytes((path) => readFileSync(path, 'utf8'))
    if (limit === null) {
        return SCRUB_WORKERS_MAX
    }
    return Math.max(1, Math.floor(limit / WORKER_MEMORY_BUDGET_BYTES))
}

/**
 * The container's memory limit in bytes, or null when the kernel reports no cap. Takes its reader
 * for the same reason quotaCores does.
 *
 * cgroup v1 reports a sentinel near 2^63 rather than a word like `max` when uncapped, and that
 * number divided by the per-worker budget is large enough to look like an unbounded allowance, so
 * anything at or above the host's own memory is treated as no limit.
 */
export function memoryLimitBytes(read: (path: string) => string): number | null {
    for (const path of ['/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes']) {
        try {
            const raw = read(path).trim()
            if (raw === 'max') {
                return null
            }
            const bytes = Number(raw)
            if (Number.isFinite(bytes) && bytes > 0 && bytes < totalmem()) {
                return bytes
            }
        } catch {
            // not this cgroup version, or not containerised
        }
    }
    return null
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
