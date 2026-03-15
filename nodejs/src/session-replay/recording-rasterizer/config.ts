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
    maxConcurrentActivities: parseInt(process.env.MAX_CONCURRENT_ACTIVITIES || '4', 10),
    browserRecycleAfter: parseInt(process.env.BROWSER_RECYCLE_AFTER || '100', 10),
    headless: process.env.RASTERIZER_HEADLESS !== '0',
    disableBrowserSecurity: process.env.DISABLE_BROWSER_SECURITY === '1',
    captureBrowserLogs: process.env.CAPTURE_BROWSER_LOGS === '1',

    // Encryption
    secretKey: process.env.DJANGO_SECRET_KEY,

    // S3
    s3Endpoint: process.env.VIDEO_EXPORT_OBJECT_STORAGE_ENDPOINT,
    s3Region: process.env.VIDEO_EXPORT_OBJECT_STORAGE_REGION || 'us-east-1',

    // Recording API
    recordingApiBaseUrl: process.env.RECORDING_API_BASE_URL || 'http://localhost:6738',
    recordingApiSecret: process.env.RECORDING_API_SECRET || '',

    // Player
    siteUrl: process.env.SITE_URL || 'http://localhost:8000',
    playerHtmlPath: process.env.PLAYER_HTML_PATH || '/code/common/replay-headless/dist/player.html',
}
