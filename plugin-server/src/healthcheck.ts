import { defaultConfig } from './config/config'
import { getObjectStorage } from './main/services/object_storage'
import { status } from './utils/status'
import { createRedis } from './utils/utils'

const redisHealthcheck = async (): Promise<boolean> => {
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

const storageHealthcheck = async (): Promise<boolean> => {
    const storage = getObjectStorage(defaultConfig)

    if (!storage) {
        return true
    }
    try {
        const storageHealthy = await storage.healthcheck()
        if (storageHealthy) {
            status.info('💚', `object storage is healthy`)
            return true
        } else {
            status.error('💔', 'object storage is not healthy')
            return false
        }
    } catch (error) {
        status.error('💥', 'Object Storage healthcheck: an unexpected error occurred:', error)
        return false
    }
}

export async function healthcheck(): Promise<boolean> {
    const redisCheck = redisHealthcheck()
    const storageCheck = storageHealthcheck()
    const [redisHealthy, storageHealthy] = await Promise.all([redisCheck, storageCheck])
    return redisHealthy && storageHealthy
}

export async function healthcheckWithExit(): Promise<never> {
    process.exit((await healthcheck()) ? 0 : 1)
}
