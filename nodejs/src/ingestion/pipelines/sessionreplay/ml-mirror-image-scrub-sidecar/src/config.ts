export interface Config {
    port: number
    // Loopback-only /scrub must not be reachable off-pod, but Prometheus scrapes the pod IP, so /metrics + health
    // live on a separate listener bound to all interfaces.
    metricsPort: number
    maxConcurrency: number
    // 413 above the ~10 MiB Kafka message ceiling — bigger is anomalous. The service owns its own memory bound.
    maxBodyBytes: number
}

export function loadConfig(): Config {
    return {
        port: Number(process.env.IMAGE_SCRUB_PORT ?? 9010),
        metricsPort: Number(process.env.IMAGE_SCRUB_METRICS_PORT ?? 9011),
        maxConcurrency: Number(process.env.IMAGE_SCRUB_CONCURRENCY ?? 8),
        maxBodyBytes: Number(process.env.IMAGE_SCRUB_MAX_BODY_BYTES ?? 20 * 1024 * 1024),
    }
}
