import os from 'node:os'

const DEFAULT_UV_THREADPOOL_SIZE = 4

/**
 * How much work the libuv threadpool can carry at once. `os.availableParallelism()` respects cgroup CPU limits, so
 * in-container this sees the pod's cores rather than the node's.
 */
export function threadpoolConcurrency(): number {
    const uvThreadpoolSize = parseInt(process.env.UV_THREADPOOL_SIZE ?? '', 10) || DEFAULT_UV_THREADPOOL_SIZE
    return Math.max(1, Math.min(os.availableParallelism(), uvThreadpoolSize))
}
