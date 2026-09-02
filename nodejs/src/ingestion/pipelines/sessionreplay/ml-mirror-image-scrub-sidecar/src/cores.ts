import { readFileSync } from 'node:fs'
import { availableParallelism, totalmem } from 'node:os'

import { numFromEnv } from './env.ts'
import { limitsFromEnv } from './scale-plan.ts'

/** Max threads a single ONNX session may use. Matches the ceiling numFromEnv enforces below. */
const ORT_THREADS_MAX = 32

/** Assumed allotment when no quota is readable. Small on purpose: see the fallback in containerCores. */
const NO_QUOTA_CORES = 4

/** Enough to cover any pod this lane is deployed on; guards a bad env value from forking hundreds. */
const SCRUB_WORKERS_MAX = 32

/**
 * Memory to assume each worker needs, derived from the frame budget it will hold rather than fixed,
 * because most of a worker's peak is the transient a scrub holds and that scales with frame area.
 * A fixed number goes stale the moment SCRUB_MAX_PIXELS moves, in whichever direction is unsafe.
 *
 * Measured with dev/mem-probe.ts, peak RSS with every worker scrubbing at once on frames at the cap:
 *
 *   cap 0.45 MP -> ~300 MB/worker      cap 2.56 MP -> ~700-780 MB/worker
 *
 * which is about 240 MB fixed (the isolate, three ONNX sessions, a zxing wasm instance) plus about
 * 240 MB per megapixel of cap. Rounded up on both terms, since sizing this low crash-loops a pod and
 * sizing it high only leaves cores idle.
 */
const WORKER_FIXED_BYTES = 288 * 1024 * 1024
const WORKER_BYTES_PER_MEGAPIXEL = 288 * 1024 * 1024
const WORKER_MEMORY_BUDGET_BYTES = WORKER_FIXED_BYTES + (WORKER_BYTES_PER_MEGAPIXEL * limitsFromEnv().framePixels) / 1e6

/**
 * Held back from the worker budget for everything that is not a worker: the main thread's own heap,
 * express and prom-client, and the overlap while a retiring worker's terminate() is still pending on
 * a native call that cannot be interrupted, which is exactly when a replacement is being started.
 * Without it the arithmetic hands every byte of the limit to workers and the guard cannot prevent
 * the OOM it exists to prevent.
 */
const MAIN_THREAD_RESERVE_BYTES = 384 * 1024 * 1024

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
 * Heap ceiling handed to each worker, so V8 sizes its isolate against its share rather than against
 * the whole container. Without it every worker independently believes it may grow into the entire
 * limit, and N of them collectively promise N times what exists: the first one to actually take it
 * gets the pod OOM-killed instead of hitting its own GC. Reported in MB, which is what
 * worker_threads' resourceLimits expects.
 */
export const WORKER_HEAP_MB = Math.max(256, Math.floor(WORKER_MEMORY_BUDGET_BYTES / (1024 * 1024)) - 128)

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

/** Workers the memory limit can hold once the main thread's reserve is set aside, or
 *  SCRUB_WORKERS_MAX when there is no limit to read: an unreadable limit must not cap the pool below
 *  what the cores support. */
export function memoryBoundedWorkers(): number {
    const limit = memoryLimitBytes((path) => readFileSync(path, 'utf8'))
    return limit === null ? SCRUB_WORKERS_MAX : workersForMemoryLimit(limit)
}

/** Split out so the arithmetic is testable without a cgroup filesystem: getting it wrong is a silent
 *  under- or over-provision rather than an error. */
export function workersForMemoryLimit(limitBytes: number): number {
    return Math.max(1, Math.floor((limitBytes - MAIN_THREAD_RESERVE_BYTES) / WORKER_MEMORY_BUDGET_BYTES))
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
