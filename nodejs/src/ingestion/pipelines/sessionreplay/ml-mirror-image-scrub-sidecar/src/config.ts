import { numFromEnv } from './env.ts'

export interface Config {
    port: number
    // Loopback-only /scrub must not be reachable off-pod, but Prometheus scrapes the pod IP, so /metrics + health
    // live on a separate listener bound to all interfaces.
    metricsPort: number
    maxConcurrency: number
    // 413 above the ~10 MiB Kafka message ceiling — bigger is anomalous. The service owns its own memory bound.
    maxBodyBytes: number
    // How long one image may hold a worker, measured from dispatch, before that worker is treated as
    // wedged and replaced. Sized against the caller that actually gives up first: ScrubClient's
    // per-request timeout is SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS (10s), not the 120s
    // whole-batch budget. Past that point the consumer has already destroyed the socket and is
    // retrying, so the work is unwanted, and every extra second it runs holds one of maxConcurrency
    // against requests that are still wanted. The slack over 10s is for the reply crossing back.
    jobTimeoutMs: number
}

// Validated like every other knob: a mistyped IMAGE_SCRUB_CONCURRENCY parsed to NaN leaves
// `inFlight >= maxConcurrency` permanently false, which removes load shedding entirely rather than
// failing loudly.
export function loadConfig(): Config {
    return {
        port: numFromEnv('IMAGE_SCRUB_PORT', 9010, 1, 65535),
        metricsPort: numFromEnv('IMAGE_SCRUB_METRICS_PORT', 9011, 1, 65535),
        maxConcurrency: numFromEnv('IMAGE_SCRUB_CONCURRENCY', 8, 1, 256),
        maxBodyBytes: numFromEnv('IMAGE_SCRUB_MAX_BODY_BYTES', 20 * 1024 * 1024, 1024, 512 * 1024 * 1024),
        jobTimeoutMs: numFromEnv('IMAGE_SCRUB_JOB_TIMEOUT_MS', 15_000, 1000, 600_000),
    }
}
