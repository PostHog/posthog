import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * Consumer for delayed invocations that waits before processing based on queueScheduledAt
 */
export class CdpCyclotronDelayConsumer extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronDelayConsumer'

    constructor(hub: Hub) {
        super(hub, 'delay_24h')
    }

    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        logger.info('⏰', `${this.name} - handling delayed batch`, {
            size: invocations.length,
        })

        // Process each invocation with its individual delay
        const processedInvocations = await Promise.all(
            invocations.map(async (invocation) => {
                if (invocation.queueScheduledAt) {
                    const now = new Date()
                    const scheduledTime = new Date(invocation.queueScheduledAt as unknown as string)

                    const delayMs = Math.max(0, scheduledTime.getTime() - now.getTime())

                    if (delayMs > 0) {
                        logger.debug('⏰', `Waiting ${delayMs}ms for delayed invocation`, {
                            invocationId: invocation.id,
                            scheduledAt: scheduledTime,
                        })

                        // Wait for the scheduled time
                        await new Promise((resolve) => setTimeout(resolve, delayMs))
                    }
                }

                // Change the queue back to 'hog' so it gets processed normally
                // The original queue information is preserved in the invocation state
                const processedInvocation = {
                    ...invocation,
                    queue: 'hog' as const,
                }

                return processedInvocation
            })
        )

        // Now process normally using the parent class implementation
        return super.processBatch(processedInvocations)
    }
}
