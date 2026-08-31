export function parseList(text: string | undefined): string[] {
    if (!text) {
        return []
    }
    return text.split(',').map((item) => item.trim())
}

// parseInt returns NaN on junk, and NaN flows silently into Worker.create / pool sizing,
// so every numeric env var goes through a fallback plus a positivity bound.
export function parsePositiveInt(raw: string | undefined, fallback: number): number {
    const n = parseInt(raw ?? '', 10)
    return Number.isFinite(n) && n > 0 ? n : fallback
}

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
    logLevel: (process.env.LOG_LEVEL || 'info') as 'debug' | 'info' | 'warn' | 'error',
    maxConcurrentActivities: parsePositiveInt(process.env.MAX_CONCURRENT_ACTIVITIES, 4),
    browserRecycleAfter: parsePositiveInt(process.env.BROWSER_RECYCLE_AFTER, 100),
    // Browsers held warm beyond this are closed on release: each idle Chromium pins 100-250MB RSS,
    // and a pod that once ran at full concurrency would otherwise keep that footprint forever.
    maxIdleBrowsers: parsePositiveInt(process.env.MAX_IDLE_BROWSERS, 2),
    disableBrowserSecurity: process.env.DISABLE_BROWSER_SECURITY === '1',
    captureBrowserLogs: process.env.CAPTURE_BROWSER_LOGS === '1',
    screenshotFormat: (process.env.SCREENSHOT_FORMAT || 'jpeg') as 'png' | 'jpeg',
    // Hard cap on a single beginFrame; mass-image-decode stalls legitimately run 30-60s, so keep
    // this well above that. It only exists to bound a truly wedged compositor.
    beginFrameTimeoutMs: parsePositiveInt(process.env.BEGINFRAME_TIMEOUT_MS, 120_000),
    screenshotJpegQuality: parsePositiveInt(process.env.SCREENSHOT_JPEG_QUALITY, 80),
    metricsPort: parsePositiveInt(process.env.METRICS_PORT, 6738),

    // Encryption
    secretKey: process.env.TEMPORAL_SECRET_KEY || process.env.SECRET_KEY,
    fallbackKeys: parseList(process.env.TEMPORAL_FALLBACK_SECRET_KEYS ?? process.env.SECRET_KEY).filter(Boolean),

    // S3
    s3Endpoint: process.env.VIDEO_EXPORT_OBJECT_STORAGE_ENDPOINT,
    s3Region: process.env.VIDEO_EXPORT_OBJECT_STORAGE_REGION || 'us-east-1',

    // Recording API. The dev recording-api listens on 6741 (bin/temporal-recording-rasterizer-worker).
    recordingApiBaseUrl: process.env.RECORDING_API_BASE_URL || 'http://localhost:6741',
    recordingApiSecret: process.env.INTERNAL_API_SECRET || '',
    // Renders above this many compressed bytes fail permanently instead of loading the pod into its
    // memory limit. Deliberately generous: the every-render byte log is what tightens it over time.
    maxRecordingCompressedBytes: parsePositiveInt(process.env.MAX_RECORDING_COMPRESSED_BYTES, 512 * 1024 * 1024),

    // Player
    siteUrl: process.env.SITE_URL || 'http://localhost:8000',
    playerHtmlPath: process.env.PLAYER_HTML_PATH || '/code/common/replay-headless/dist/player.html',
    // Serve the player under a script-locking CSP (nonce). On by default: recordings are untrusted,
    // and the CSP is the backstop if the replay iframe sandbox ever regresses. ENABLE_PLAYER_CSP=0
    // is the escape hatch if a player build ships without the nonce placeholder.
    enablePlayerCsp: process.env.ENABLE_PLAYER_CSP !== '0',
}
