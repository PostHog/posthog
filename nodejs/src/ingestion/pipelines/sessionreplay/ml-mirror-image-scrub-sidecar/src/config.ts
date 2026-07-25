import { numFromEnv } from './env.ts'

export interface Config {
    port: number
    // Loopback-only /scrub must not be reachable off-pod, but Prometheus scrapes the pod IP, so /metrics + health
    // live on a separate listener bound to all interfaces.
    metricsPort: number
    maxConcurrency: number
    // 413 above the ~10 MiB Kafka message ceiling — bigger is anomalous. The service owns its own memory bound.
    maxBodyBytes: number
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
    }
}
