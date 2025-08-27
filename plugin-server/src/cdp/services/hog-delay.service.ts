import { CyclotronJobInvocation, CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'

/**
 * Service for handling delayed invocations
 */
export class HogDelayService {
    constructor(private maxDelayMs: number) {}

    public async processBatchWithDelay(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const now = new Date()
        let firstDelayMs: number | null = null

        const processedInvocations: CyclotronJobInvocationResult[] = []

        for (const invocation of invocations) {
            if (invocation.queueScheduledAt) {
                const scheduledTime = new Date(invocation.queueScheduledAt as unknown as string)
                let delayMs = Math.max(0, scheduledTime.getTime() - now.getTime())

                if (firstDelayMs === null) {
                    firstDelayMs = delayMs
                    const waitTime = Math.min(firstDelayMs, this.maxDelayMs)

                    console.log(`Waiting for ${waitTime}ms before processing invocation ${invocation.id}`)

                    await new Promise((resolve) => setTimeout(resolve, waitTime))

                    delayMs = 0
                }

                console.log(`Processing invocation ${invocation.id}. Delay is ${delayMs}ms`)

                processedInvocations.push(
                    createInvocationResult<CyclotronJobInvocationHogFunction>(
                        {
                            ...invocation,
                            queue: delayMs === 0 ? 'hog' : 'delay_24h',
                        },
                        {},
                        { finished: false }
                    )
                )
            }
        }

        return processedInvocations
    }
}
