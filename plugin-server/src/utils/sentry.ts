const fs = require('fs')

import * as Sentry from '@sentry/node'

import { PluginsServerConfig } from '../types'

// Code that runs on app start, in both the main and worker threads
export function initSentry(config: PluginsServerConfig): void {
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
        initialScope: {
            tags: {
                PLUGIN_SERVER_MODE: config.PLUGIN_SERVER_MODE,
                DEPLOYMENT: config.CLOUD_DEPLOYMENT,
                PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE: config.PLUGIN_SERVER_EVENTS_INGESTION_PIPELINE,
            },
        },
        release,
    })
}
