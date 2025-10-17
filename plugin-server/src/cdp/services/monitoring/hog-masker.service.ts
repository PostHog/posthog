import { createHash } from 'crypto'

import { CdpRedis } from '../../redis'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    HogFunctionMasking,
} from '../../types'
import { execHog } from '../../utils/hog-exec'

export const BASE_REDIS_KEY = process.env.NODE_ENV == 'test' ? '@posthog-test/hog-masker' : '@posthog/hog-masker'
const REDIS_KEY_TOKENS = `${BASE_REDIS_KEY}/mask`

// NOTE: These are controlled via the api so are more of a sanity fallback
const MASKER_MAX_TTL = 60 * 60 * 24
const MASKER_MIN_TTL = 1

type MaskContext = {
    hogFunctionId: string
    hash: string
    increment: number
    ttl: number
    allowedExecutions: number
    threshold: number | null
}

type GenericHogInvocationWithMasker = CyclotronJobInvocation & {
    masker?: MaskContext
}

function isHogFunctionInvocation(invocation: CyclotronJobInvocation): invocation is CyclotronJobInvocationHogFunction {
    return (invocation as CyclotronJobInvocationHogFunction).hogFunction !== undefined
}

function isHogFlowInvocation(invocation: CyclotronJobInvocation): invocation is CyclotronJobInvocationHogFlow {
    return (invocation as CyclotronJobInvocationHogFlow).hogFlow !== undefined
}

// Helper to extract masking config from different types
function extractMaskingConfig(invocation: CyclotronJobInvocation): HogFunctionMasking | null {
    if (isHogFunctionInvocation(invocation)) {
        return invocation.hogFunction.masking || null
    }

    if (isHogFlowInvocation(invocation)) {
        return invocation.hogFlow.trigger_masking || null
    }

    throw new Error('Unable to extract masking config from unknown invocation type')
}

function extractGlobals(invocation: CyclotronJobInvocation): Record<string, any> {
    if (isHogFunctionInvocation(invocation)) {
        return invocation.state.globals
    }
    if (isHogFlowInvocation(invocation)) {
        // For hog flows, we need to construct globals from the filter globals and event
        return {
            event: invocation.state?.event,
            person: invocation.person,
        }
    }

    throw new Error('Unable to extract globals from unknown invocation type')
}

// Helper to get entity ID for masking
function getEntityId(invocation: CyclotronJobInvocation): string {
    if (isHogFunctionInvocation(invocation)) {
        return invocation.hogFunction.id
    }
    if (isHogFlowInvocation(invocation)) {
        return invocation.hogFlow.id
    }
    return invocation.functionId
}

/**
 * HogMaskerService
 *
 * Responsible for determining if a function is "masked" or not based on the function configuration
 */

// Hog masker is meant to be done per batch
export class HogMaskerService {
    constructor(private redis: CdpRedis) {}

    public async filterByMasking<T extends CyclotronJobInvocation>(
        invocations: T[]
    ): Promise<{
        masked: T[]
        notMasked: T[]
    }> {
        const invocationsWithMasker: GenericHogInvocationWithMasker[] = [...invocations]
        const masks: Record<string, MaskContext> = {}

        // We find all functions/flows that have a mask and we load their masking from redis
        for (const item of invocationsWithMasker) {
            const maskingConfig = extractMaskingConfig(item)
            if (maskingConfig) {
                const globals = extractGlobals(item)

                // TODO: Catch errors
                const execHogResult = await execHog(maskingConfig.bytecode, {
                    globals,
                    timeout: 50,
                })

                if (!execHogResult.execResult?.result) {
                    continue
                }
                // What to do if it is null....

                const hash = createHash('md5')
                    .update(String(execHogResult.execResult.result))
                    .digest('hex')
                    .substring(0, 32)
                const entityId = getEntityId(item)
                const hashKey = `${entityId}:${hash}`
                masks[hashKey] = masks[hashKey] || {
                    hash,
                    hogFunctionId: entityId,
                    increment: 0,
                    ttl: Math.max(MASKER_MIN_TTL, Math.min(MASKER_MAX_TTL, maskingConfig.ttl ?? MASKER_MAX_TTL)),
                    threshold: maskingConfig.threshold,
                    allowedExecutions: 0,
                }
                masks[hashKey]!.increment++
                item.masker = masks[hashKey]
            }
        }

        if (Object.keys(masks).length === 0) {
            return { masked: [], notMasked: invocations }
        }

        const result = await this.redis.usePipeline({ name: 'masker', failOpen: true }, (pipeline) => {
            Object.values(masks).forEach(({ hogFunctionId, hash, increment, ttl }) => {
                pipeline.incrby(`${REDIS_KEY_TOKENS}/${hogFunctionId}/${hash}`, increment)
                // @ts-expect-error - NX is not typed in ioredis
                pipeline.expire(`${REDIS_KEY_TOKENS}/${hogFunctionId}/${hash}`, ttl, 'NX')
            })
        })

        Object.values(masks).forEach((masker, index) => {
            const newValue: number | null = result ? result[index * 2][1] : null
            if (newValue === null) {
                // We fail closed here as with a masking config the typical case will be not to send
                return
            }

            const oldValue = newValue - masker.increment

            // Simplest case - the previous value was 0
            masker.allowedExecutions = oldValue === 0 ? 1 : 0

            if (masker.threshold) {
                // TRICKY: We minus 1 to account for the "first" execution
                const thresholdsPasses =
                    Math.floor((newValue - 1) / masker.threshold) - Math.floor((oldValue - 1) / masker.threshold)

                if (thresholdsPasses) {
                    masker.allowedExecutions = thresholdsPasses
                }
            }
        })

        return invocationsWithMasker.reduce(
            (acc, item) => {
                if (item.masker) {
                    if (item.masker.allowedExecutions > 0) {
                        item.masker.allowedExecutions--
                        acc.notMasked.push(item as T)
                    } else {
                        acc.masked.push(item as T)
                    }
                } else {
                    acc.notMasked.push(item as T)
                }
                return acc
            },
            { masked: [], notMasked: [] } as {
                masked: T[]
                notMasked: T[]
            }
        )
    }
}
