const fs = require('fs')

import * as Sentry from '@sentry/node'
import { ProfilingIntegration } from '@sentry/profiling-node'

import { PluginsServerConfig } from '../types'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// Code that runs on app start, in both the main and worker threads
export function initSentry(config: PluginsServerConfig): void {
    if (config.SENTRY_DSN) {
        const integrations = []
        if (config.SENTRY_PLUGIN_SERVER_PROFILING_SAMPLE_RATE > 0) {
            integrations.push(new ProfilingIntegration())
        }

        let release: string | undefined = undefined
        try {
            // Docker containers should have a commit.txt file in the base directory with the git
            // commit hash used to generate them. `plugin-server` runs from a child directory, so we
            // need to look up one level.
            release = fs.readFileSync('../commit.txt', 'utf8')
        } catch (error) {
            // The release isn't required, it's just nice to have.
        }

        Sentry.init({
            dsn: config.SENTRY_DSN,
            normalizeDepth: 8, // Default: 3
            initialScope: {
                tags: {
                    PLUGIN_SERVER_MODE: config.PLUGIN_SERVER_MODE,
                    DEPLOYMENT: config.CLOUD_DEPLOYMENT,
                    PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: config.PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE,
                },
            },
            release,
            integrations,
            tracesSampleRate: config.SENTRY_PLUGIN_SERVER_TRACING_SAMPLE_RATE,
            profilesSampleRate: config.SENTRY_PLUGIN_SERVER_PROFILING_SAMPLE_RATE,
        })
    }
}
