export const config = {
    // Temporal
    temporalHost: process.env.TEMPORAL_HOST || '127.0.0.1',
    temporalPort: process.env.TEMPORAL_PORT || '7233',
    temporalNamespace: process.env.TEMPORAL_NAMESPACE || 'default',
    taskQueue: process.env.TEMPORAL_TASK_QUEUE || 'rasterization-task-queue',
    temporalClientRootCA: process.env.TEMPORAL_CLIENT_ROOT_CA,
    temporalClientCert: process.env.TEMPORAL_CLIENT_CERT,
    temporalClientKey: process.env.TEMPORAL_CLIENT_KEY,

    // Worker
    maxConcurrentActivities: parseInt(process.env.MAX_CONCURRENT_ACTIVITIES || '10', 10),
    browserRecycleAfter: parseInt(process.env.BROWSER_RECYCLE_AFTER || '100', 10),
    headless: process.env.EXPORTER_HEADLESS !== '0',

    // Encryption
    secretKey: process.env.DJANGO_SECRET_KEY,

    // S3
    s3Endpoint: process.env.VIDEO_EXPORT_OBJECT_STORAGE_ENDPOINT,
    s3Region: process.env.VIDEO_EXPORT_OBJECT_STORAGE_REGION || 'us-east-1',
}
