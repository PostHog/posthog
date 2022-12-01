import Redis from 'ioredis'
import { Client } from 'pg'

import { defaultConfig } from '../src/config/config'

export default async function () {
    // To avoid any plugins that may be registered from previous test runs
    // making tests noisy, we disable all plugins before running tests. The
    // individual tests will create any plugins they need.

    const postgres = new Client({ connectionString: defaultConfig.DATABASE_URL! })
    const redis = new Redis(defaultConfig.REDIS_URL)

    try {
        await postgres.connect()
        await postgres.query('UPDATE posthog_pluginconfig SET enabled = false WHERE enabled = true;')
        await redis.publish('reload-plugins', '')
    } finally {
        await Promise.all([postgres.end(), redis.disconnect()])
    }
}
