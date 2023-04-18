import path from 'path'

export const config = {
    port: process.env.PORT || 8010,
    logLevel: process.env.LOG_LEVEL || 'info',

    topics: {
        sessionRecordingEvents: process.env.SESSION_RECORDING_EVENTS || 'session_recording_events',
        sessionRecordingEventsDeadLetter:
            process.env.SESSION_RECORDING_EVENTS_DEAD_LETTER || 'session_recording_events_dead_letter',
    },

    s3: {
        // NOTE: Use process.env.NODE_ENV to decide on defaults
        endpoint: process.env.OBJECT_STORAGE_ENDPOINT || 'http://localhost:19000',
        accessKeyId: process.env.OBJECT_STORAGE_ACCESS_KEY_ID || 'object_storage_root_user',
        secretAccessKey: process.env.OBJECT_STORAGE_SECRET_ACCESS_KEY || 'object_storage_root_password',
        region: process.env.OBJECT_STORAGE_REGION || 'us-east-1',
        bucket: process.env.OBJECT_STORAGE_BUCKET || 'posthog',
        sessionRecordingFolder: process.env.OBJECT_STORAGE_SESSION_RECORDING_FOLDER || 'session_recordings',
    },

    consumerConfig: {
        groupId: `object-storage-ingester`,
        sessionTimeout: 30000,
        heartbeatInterval: 6000,
    },

    sessions: {
        directory: process.env.SESSIONS_DIRECTORY || path.join(__dirname, '.tmp/sessions'),
        // NOTE: 10 minutes
        maxEventGroupAgeSeconds: Number.parseInt(process.env.MAX_EVENT_GROUP_AGE) || 60 * 10,
        // NOTE: ~1MB in dev, ~50MB in prod
        maxEventGroupKb:
            Number.parseInt(process.env.MAX_EVENT_GROUP_SIZE) || (process.env.NODE_ENV === 'dev' ? 100 : 1000 * 50),
    },
}
