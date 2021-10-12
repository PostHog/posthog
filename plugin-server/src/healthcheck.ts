import { defaultConfig } from './config/config'
import { status } from './utils/status'
import { createRedis } from './utils/utils'

export async function healthcheck(): Promise<boolean> {
    const redis = await createRedis(defaultConfig)
    try {
        const ping = await redis.get('@posthog-plugin-server/ping')
        if (ping) {
            status.info('💚', `Redis key @posthog-plugin-server/ping found with value ${ping}`)
            return true
        } else {
            status.error('💔', 'Redis key @posthog-plugin-server/ping not found! Plugin server seems to be offline')
            return false
        }
    } catch (error) {
        status.error('💥', 'An unexpected error occurred:', error)
        return false
    } finally {
        redis.disconnect()
    }
}

export async function healthcheckWithExit(): Promise<never> {
    process.exit((await healthcheck()) ? 0 : 1)
}
