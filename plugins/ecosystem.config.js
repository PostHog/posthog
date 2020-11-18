module.exports = {
    apps: [
        {
            script: 'posthog-plugin-server',
            instances: process.env.WEB_CONCURRENCY || 'max',
            args: ['start', '--config', process.env.CONF || '{}'],
        },
    ],
}
