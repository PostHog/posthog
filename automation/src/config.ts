export const config = {
    port: process.env.PORT || 8011,
    logLevel: process.env.LOG_LEVEL || 'info',

    topics: {
        captureEvents: process.env.TOPIC_CAPTURE_EVENTS || 'clickhouse_events_json',
    },

    consumerConfig: {
        groupId: process.env.KAFKA_GROUP_ID || 'automation_events_ingester',
        sessionTimeout: 30000,
        heartbeatInterval: 6000,
    },

    postgres: {
        databaseUrl: process.env.DATABASE_URL || 'postgres://posthog:posthog@db:5432/posthog',
    },
}
