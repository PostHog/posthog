import { exec } from '@posthog/hogvm'
import { createHash } from 'crypto'

import { CdpRedis } from './redis'
import { HogFunctionInvocationGlobals, HogFunctionType } from './types'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-masker' : '@posthog/hog-masker'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/mask`

const MASKER_MAX_TTL = 60 * 60 * 24
const MASKER_MIN_TTL = 60

type MaskContext = {
    hogFunctionId: string
    hash: string
    increment: number
    ttl: number
    allowedExecutions: number
}

type HogInvocationContext = {
    globals: HogFunctionInvocationGlobals
    hogFunction: HogFunctionType
}

type HogInvocationContextWithMasker = HogInvocationContext & {
    masker?: MaskContext
}

/**
 * HogMasker
 *
 * Responsible for determining if a function is "masked" or not based on the function configuration
 */

// Hog masker is meant to be done per batch
export class HogMasker {
    constructor(private redis: CdpRedis) {}

    // private async runRedis<T>(fn: (client: Redis) => Promise<T>): Promise<T | null> {

    //     // We want all of this to fail open in the issue of redis being unavailable - we'd rather have the function continue
    //     const client = await this.hub.redisPool.acquire()

    //     const timeout = timeoutGuard(`Redis call delayed. Waiting over 30 seconds.`, undefined, 30 * 1000)
    //     try {
    //         return await fn(client)
    //     } catch (e) {
    //         status.error('HogWatcher Redis error', e)
    //         captureException(e)
    //         return null
    //     } finally {
    //         clearTimeout(timeout)
    //         await this.hub.redisPool.release(client)
    //     }
    // }

    public async filterByMasking(invocations: HogInvocationContext[]): Promise<{
        masked: HogInvocationContext[]
        notMasked: HogInvocationContext[]
    }> {
        const invocationsWithMasker: HogInvocationContextWithMasker[] = [...invocations]
        const masks: Record<string, MaskContext> = {}

        // We find all functions that have a mask and we load their masking from redis
        invocationsWithMasker.forEach((item) => {
            if (item.hogFunction.masking) {
                // TODO: Catch errors
                const value = exec(item.hogFunction.masking.bytecode, {
                    globals: item.globals,
                    timeout: 50,
                    maxAsyncSteps: 0,
                })
                // What to do if it is null....
                const hash = createHash('md5').update(String(value.result)).digest('hex').substring(0, 32)
                const hashKey = `${item.hogFunction.id}:${hash}`
                masks[hashKey] = masks[hashKey] || {
                    hash,
                    hogFunctionId: item.hogFunction.id,
                    increment: 0,
                    ttl: Math.max(
                        MASKER_MIN_TTL,
                        Math.min(MASKER_MAX_TTL, item.hogFunction.masking.ttl ?? MASKER_MAX_TTL)
                    ),
                    allowedExecutions: 0,
                }

                masks[hashKey]!.increment++
                item.masker = masks[hashKey]
            }
        })

        if (Object.keys(masks).length === 0) {
            return { masked: [], notMasked: invocations }
        }

        // Load from redis returning the value - this allows us to compare - if the value is the same then we allow an invocation
        const result = await this.redis.usePipeline({ name: 'masker', failOpen: true }, (pipeline) => {
            Object.values(masks).forEach(({ hash, increment, ttl }) => {
                pipeline.incrby(`${REDIS_KEY_TOKENS}/${hash}`, increment)
                // @ts-expect-error - NX is not typed in ioredis
                pipeline.expire(`${REDIS_KEY_TOKENS}/${hash}`, ttl, 'NX')
            })
        })

        Object.values(masks).forEach((masker, index) => {
            const fromRedis = result ? result[index][1] : 0 // Here we want to fail closed as flooding messages is likely not good!

            // If increment matches the result then there was no previous result - we can permit one invocation

            if (fromRedis === masker.increment) {
                masker.allowedExecutions = 1
            }
        })

        return invocationsWithMasker.reduce(
            (acc, item) => {
                if (item.masker) {
                    if (item.masker.allowedExecutions > 0) {
                        item.masker.allowedExecutions--
                        acc.notMasked.push(item)
                    } else {
                        acc.masked.push(item)
                    }
                } else {
                    acc.notMasked.push(item)
                }
                return acc
            },
            { masked: [], notMasked: [] } as { masked: HogInvocationContext[]; notMasked: HogInvocationContext[] }
        )
    }
}
