export interface Config {
    port: number
    maxConcurrency: number
    // 413 above the ~10 MiB Kafka message ceiling — bigger is anomalous. The service owns its own memory bound.
    maxBodyBytes: number
}

export function loadConfig(): Config {
    return {
        port: Number(process.env.IMAGE_SCRUB_PORT ?? 9010),
        maxConcurrency: Number(process.env.IMAGE_SCRUB_CONCURRENCY ?? 8),
        maxBodyBytes: Number(process.env.IMAGE_SCRUB_MAX_BODY_BYTES ?? 20 * 1024 * 1024),
    }
}
