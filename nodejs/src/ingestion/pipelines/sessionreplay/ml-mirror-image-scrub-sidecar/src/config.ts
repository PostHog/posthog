import { SCRUB_WORKERS } from './cores.ts'
import { numFromEnv } from './env.ts'

/**
 * Requests admitted per worker.
 *
 * One would leave a worker idle for the width of a request body while the next one is read, so the
 * spare slot per worker is what keeps them fed. More than that is queue, and queue is the thing to
 * avoid: an admitted request produces no bytes until a worker frees up, and the consumer's timeout
 * is an inactivity timeout, so queueing reads to it as an unresponsive sidecar rather than as a busy
 * one. Shedding early gives it a 503 it can act on immediately.
 */
const ADMITTED_PER_WORKER = 2

export interface Config {
    port: number
    // Loopback-only /scrub must not be reachable off-pod, but Prometheus scrapes the pod IP, so /metrics + health
    // live on a separate listener bound to all interfaces.
    metricsPort: number
    maxConcurrency: number
    // 413 above the ~10 MiB Kafka message ceiling — bigger is anomalous. The service owns its own memory bound.
    maxBodyBytes: number
    // How long one image may hold a worker, measured from dispatch, before that worker is treated as
    // wedged and replaced. This must stay BELOW the consumer's per-request timeout
    // (SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS): giving up here first is what turns an
    // image this sidecar cannot finish into a 500, which is a considered answer about that image and
    // is what lets the consumer blame it and park it. If the consumer gave up first the image would
    // look merely slow forever and hold the head of its partition. Measured from dispatch rather
    // than enqueue so queue wait is not charged to whichever worker happens to hold the job.
    jobTimeoutMs: number
}

export function loadConfig(): Config {
    return {
        port: numFromEnv('IMAGE_SCRUB_PORT', 9010, 1, 65535),
        metricsPort: numFromEnv('IMAGE_SCRUB_METRICS_PORT', 9011, 1, 65535),
        maxConcurrency: ADMITTED_PER_WORKER * SCRUB_WORKERS,
        maxBodyBytes: numFromEnv('IMAGE_SCRUB_MAX_BODY_BYTES', 20 * 1024 * 1024, 1024, 512 * 1024 * 1024),
        jobTimeoutMs: numFromEnv('IMAGE_SCRUB_JOB_TIMEOUT_MS', 15_000, 1000, 600_000),
    }
}
